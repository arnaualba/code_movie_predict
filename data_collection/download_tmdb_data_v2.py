#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
This code is almost entirely copied from https://gist.github.com/SohierDane/4a84cb96d220fc4791f52562be37968b

Pull movie metadata from the https://www.themoviedb.org API.

It only pulls movies that are already in the database full_data.csv

Requires an API key stored in a .config file
i.e. you must have a file .config in the same directory as 
this script, with the following content:

{
  "api_key" : "your_api_key_goes_here"
}

You can get an API key by creating an account at www.themoviedb.org,
or by asking Arnau :D (j'ai fait un compte donc on peut tous utiliser la même clé)

Please see attribution requirements here before posting data:
    https://www.themoviedb.org/faq/api

API documentation:
    https://developers.themoviedb.org/3/getting-started
    https://www.themoviedb.org/documentation/api
"""


import gzip
import json
import os
import pandas as pd
import requests

from io import BytesIO
from time import sleep


BASE_API_CALL = 'https://api.themoviedb.org/3/movie/{entry_id}?api_key={api_key}{category_specifics}'
DOWNLOADS_PER_DISK_WRITE = 40
MAX_DOWNLOADS_PER_SECOND = 4
MAX_ATTEMPTS = 3
RATE_LIMITER_DELAY_SECONDS = 10
RATE_LIMIT_EXCEEDED_STATUS_CODE = 429
SUCCESSFUL_CALL_STATUS_CODE = 200

data_folder = '../data2/'
if not (os.path.exists(data_folder)):
    os.popen('mkdir ' + data_folder)   

CATEGORY_SPECIFIC_CALLS = {
    #~ 'movie': '&append_to_response=credits,keywords',
    'movie': '&append_to_response=keywords',
                            }

JSON_COLUMNS = {
    'genres',
    'keywords',
    'production_countries',
    'production_companies',
    'spoken_languages'
                }

KEYS_TO_DROP = {
    'adult',
    'backdrop_path',
    'belongs_to_collection',
    'poster_path',
    'profile_path',
    'video',
                }


def was_successful(response):
    return response.status_code == SUCCESSFUL_CALL_STATUS_CODE


def was_rate_limited(response):
    return response.status_code == RATE_LIMIT_EXCEEDED_STATUS_CODE


def make_request(call_url, prior_attempts=0):
    if prior_attempts >= MAX_ATTEMPTS:
        return None
    response = requests.get(call_url)
    if was_rate_limited(response):
        sleep(RATE_LIMITER_DELAY_SECONDS)
    sleep(1 / MAX_DOWNLOADS_PER_SECOND)
    if was_successful(response):
        return response.json()
    else:
        sleep(1)  # attempt to sleep through any intermittent issues
        return make_request(call_url, prior_attempts + 1)


def make_detail_request(category, entry_id):
    category_specifics = ''
    if category in CATEGORY_SPECIFIC_CALLS:
        category_specifics = CATEGORY_SPECIFIC_CALLS[category]
    call_url = BASE_API_CALL.format(
        #~ category=category,
        entry_id=entry_id,
        api_key=API_KEY,
        category_specifics=category_specifics,
                                    )
    return make_request(call_url)


def load_api_key():
    return json.load(open('.config'))['api_key']


def make_category_id_url_suffix(category, extension='json'):
    year = str(pd.datetime.today().year)
    month = str(pd.datetime.today().month).zfill(2)
    day = str(pd.datetime.today().day - 1).zfill(2)
    return '_'.join([category, 'ids', month, day, year]) + '.' + extension


def download_id_list_as_csv(category):
    # see daily file export list docs at:
    # https://developers.themoviedb.org/3/getting-started/daily-file-exports
    print('Downloading list of ids for', category)
    id_list_name = make_category_id_url_suffix(category)
    ID_LISTS_RAW_URL = 'http://files.tmdb.org/p/exports/{0}.gz'.format(id_list_name)
    with gzip.open(BytesIO(requests.get(ID_LISTS_RAW_URL).content), 'r') as f_open:
        id_list = []
        for line in f_open:
          id_list.append(line.decode('utf-8'))
    # original 'json' is malformed, is actually one dict per line
    ids = pd.DataFrame([json.loads(x) for x in id_list])
    # some entries in the movie id list appear to be collections rather than movies
    if 'original_title' in ids.columns:
        ids.original_title = ids.original_title.apply(str)
        ids = ids[~ids.original_title.str.endswith(' Collection')].copy()
    ids.to_csv(data_folder + category + '_ids.csv', index=False)


def load_id_list(category):
    download_id_list_as_csv(category)
    df = pd.read_csv(data_folder + category + '_ids.csv')
    mv = pd.read_csv('../full_data.csv')
    df = df[df['original_title'].isin(mv['primaryTitle'])]
    df.to_csv(path_or_buf = data_folder + category + '_ids.csv')
    return df.id.values.tolist()


def unpack_credits(df):
    # credits were downloaded with the movie details to cut down on the
    # total number of requests, but it should probably be stored separately
    credits = pd.DataFrame(df[['credits', 'id', 'title']])
    credits.rename(columns={'id': 'movie_id'}, inplace=True)
    new_columns = ['cast', 'crew']
    for column in new_columns:
        credits[column] = credits['credits'].apply(
            lambda x: x[column] if column in x else [])
        credits[column] = credits[column].apply(lambda x:
            [{k: v for k, v in i.items() if k not in {'profile_path'}} for i in x])
        credits[column] = credits[column].apply(json.dumps)
    del credits['credits']
    del df['credits']
    return df, credits


def export_data(category, all_entries):
    if not all_entries:
        return None
    df = pd.DataFrame(all_entries)
    df = df[[x for x in df.columns if x not in KEYS_TO_DROP]].copy()
    if len(df[df.id.isnull()]) > 0:
        print('Dropping', len(df[df.id.isnull()]), 'entries without ids')
        df = df[~df.id.isnull()]
    df = df[df.id.apply(lambda x: str(x).isnumeric())]
    # this section about credits is specific to the movie category
    #~ df, credits = unpack_credits(df)
    df['keywords'] = df['keywords'].apply(lambda x:
        x['keywords'] if 'keywords' in x else [])
    for column in JSON_COLUMNS:
        df[column] = df[column].apply(json.dumps)
    needs_header = not(os.path.exists(data_folder + category + '_data.csv'))
    df.to_csv(data_folder + category + '_data.csv', index=False, mode='a+', header=needs_header)
    #~ credits.to_csv(data_folder + category + '_credits.csv', index=False, mode='a+', header=needs_header)


def download_ids(category, id_list):
    if os.path.exists(data_folder + category + '_data.csv'):
        existing_ids = pd.read_csv(data_folder + category + '_data.csv', usecols=['id'], dtype=object)
        set(existing_ids.id.values.tolist())
        id_list = [x for x in id_list if str(x) not in existing_ids]
    counter = 0
    all_entries = []
    print('Downloading details for', category)
    for movie_id in id_list:
        current_data = make_detail_request(category, movie_id)
        if not current_data:
            print('Failed on id #', movie_id)
            continue
        counter += 1
        all_entries.append(current_data)
        if counter % DOWNLOADS_PER_DISK_WRITE == 0:
            print('Finished downloading',counter, 'entries for', category)
            export_data(category, all_entries)
            all_entries = []
    export_data(category, all_entries)


def download_all_data():
    download_ids('movie', load_id_list('movie'))


if __name__ == '__main__':
    API_KEY = load_api_key()
    download_all_data()
