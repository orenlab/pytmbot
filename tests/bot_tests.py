#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import unittest

import requests
import responses


class TestCase(unittest.TestCase):

    @responses.activate
    def test_glances_api_status(self):
        responses.add(**{
            'method': responses.GET,
            'url': 'http://localhost:61208/api/3/status',
            'body': 'Active',
            'status': 200,
            'content_type': 'text',
        })

        response = requests.get('http://localhost:61208/api/3/status', timeout=10)

        self.assertEqual('Active', response.text)
        self.assertEqual(200, response.status_code)
