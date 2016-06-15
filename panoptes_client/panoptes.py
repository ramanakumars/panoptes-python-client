import requests

from datetime import datetime, timedelta

class Panoptes(object):
    _client = None

    _http_headers = {
        'default': {
            'Accept': 'application/vnd.api+json; version=1',
        },
        'GET': {},
        'PUT': {
            'Content-Type': 'application/json',
        },
        'POST': {
            'Content-Type': 'application/json',
        },
    }

    _endpoint_client_ids = {
        'default': (
            'f79cf5ea821bb161d8cbb52d061ab9a2321d7cb169007003af66b43f7b79ce2a'
        ),
    }

    @classmethod
    def connect(cls, *args, **kwargs):
        return cls(*args, **kwargs)

    @classmethod
    def client(cls):
        if not cls._client:
            cls._client = cls()
        return cls._client

    def __init__(
        self,
        endpoint='https://panoptes.zooniverse.org',
        client_id=None,
        username=None,
        password=None
    ):
        Panoptes._client = self

        self.endpoint = endpoint
        self.username = username
        self.password = password

        if client_id:
            self.client_id = client_id
        else:
            self.client_id = self._endpoint_client_ids.get(
                self.endpoint,
                self._endpoint_client_ids['default']
            )

        self.logged_in = False
        self.bearer_token = None

        self.session = requests.session()

    def http_request(
        self,
        method,
        path,
        params={},
        headers={},
        json={},
        etag=None
    ):
        _headers = self._http_headers['default'].copy()
        _headers.update(self._http_headers[method])
        _headers.update(headers)
        headers = _headers

        token = self.get_bearer_token()
        if self.logged_in:
            headers.update({
                'Authorization': 'Bearer %s' % token,
            })

        if etag:
            headers.update({
                'If-Match': etag,
            })

        url = self.endpoint + '/api' + path
        response = self.session.request(
            method,
            url,
            params=params,
            headers=headers,
            json=json
        )
        if response.status_code >= 500:
            raise PanoptesAPIException(
                'Received HTTP status code {} from API'.format(
                    response.status_code
                )
            )
        return response

    def json_request(
        self,
        method,
        path,
        params={},
        headers={},
        json={},
        etag=None
    ):
        response = self.http_request(method, path, params, headers, json, etag)
        json_response = response.json()
        if 'errors' in json_response:
            raise PanoptesAPIException(', '.join(
                map(lambda e: e.get('message', ''),
                    json_response['errors']
                   )
            ))
        return (json_response, response.headers.get('ETag'))

    def get_request(self, path, params={}, headers={}):
        return self.http_request('GET', path, params, headers)

    def get(self, path, params={}, headers={}):
        return self.json_request('GET', path, params, headers)

    def put_request(self, path, params={}, headers={}, json={}, etag=None):
        return self.http_request(
            'PUT',
            path,
            params,
            headers,
            json=json,
            etag=etag
        )

    def put(self, path, params={}, headers={}, json={}, etag=None):
        return self.json_request(
            'PUT',
            path,
            params,
            headers,
            json=json,
            etag=etag
        )

    def post_request(self, path, params={}, headers={}, json={}, etag=None):
        return self.http_request(
            'post',
            path,
            params=params,
            headers=headers,
            json=json,
            etag=etag
        )

    def post(self, path, params={}, headers={}, json={}, etag=None):
        return self.json_request('POST', path, params, headers, json, etag)

    def login(self, username=None, password=None):
        if not username:
            username = self.username
        else:
            self.username = username

        if not password:
            password = self.password
        else:
            self.password = password

        if not username or not password:
            return

        login_data = {
            'authenticity_token': self.get_csrf_token(),
            'user': {
                'login': username,
                'password': password,
                'remember_me': True,
            },
        }
        response = self.session.post(
            self.endpoint + '/users/sign_in',
            json=login_data,
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
        )
        if response.status_code != 200:
            raise PanoptesAPIException(
                response.json().get('error', 'Login failed')
            )
        self.logged_in = True
        return response

    def get_csrf_token(self):
        url = self.endpoint + '/users/sign_in'
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        return self.session.get(url, headers=headers).headers['x-csrf-token']

    def get_bearer_token(self):
        if not self.bearer_token or self.bearer_expires > datetime.now():
            if not self.logged_in:
                if not self.login():
                    return
            if self.bearer_token:
                bearer_data = {
                    'grant_type': 'refresh_token',
                    'refresh_token': self.refresh_token,
                    'client_id': self.client_id,
                }
            else:
                bearer_data = {
                    'grant_type': 'password',
                    'client_id': self.client_id,
                }
            token_response = self.session.post(
                self.endpoint + '/oauth/token',
                bearer_data
            ).json()
            if 'errors' in token_response:
                raise PanoptesAPIException(token_response['errors'])
            self.bearer_token = token_response['access_token']
            self.refresh_token = token_response['refresh_token']
            self.bearer_expires = (
                datetime.now()
                + timedelta(seconds=token_response['expires_in'])
            )
        return self.bearer_token

class PanoptesObject(object):
    @classmethod
    def url(cls, *args):
        return '/'.join(['', cls._api_slug] + [ unicode(a) for a in args if a ])

    @classmethod
    def get(cls, path, params={}, headers={}):
        return Panoptes.client().get(
            cls.url(path),
            params,
            headers
        )

    @classmethod
    def find(cls, _id, params={}):
        if _id is None:
            _id = ''
        return cls.paginated_results(*cls.get(_id, params=params))

    @classmethod
    def paginated_results(cls, response, etag):
        return ResultPaginator(cls, response, etag)

    def __init__(self, raw={}, etag=None):
        self.set_raw(raw, etag)

    def __getattr__(self, name):
        try:
            return self.raw[name]
        except KeyError:
            if name == 'id':
                return None
            raise AttributeError("'%s' object has no attribute '%s'" % (
                self.__class__.__name__,
                name
            ))

    def __setattr__(self, name, value):
        reserved_names = ('raw', 'links')
        if name not in reserved_names and name in self.raw:
            if name not in self._edit_attributes:
                raise ReadOnlyAttributeException(
                    '{} is read-only'.format(name)
                )
            self.raw[name] = value
            self.modified_attributes.add(name)
        else:
            super(PanoptesObject, self).__setattr__(name, value)

    def __repr__(self):
        return '<{} {}>'.format(
            self.__class__.__name__,
            self.id
        )

    def set_raw(self, raw, etag=None):
        self.raw = {}
        self.raw.update(self._savable_dict(include_none=True))
        self.raw.update(raw)
        self.etag = etag
        self.modified_attributes = set()

        if 'links' in self.raw:
            self.links = LinkResolver(self.raw['links'])

    def _savable_dict(
        self,
        attributes=None,
        modified_attributes=None,
        include_none=False,
    ):
        if not attributes:
            attributes = self._edit_attributes
        out = []
        for key in attributes:
            if type(key) == dict:
                for subkey, subattributes in key.items():
                    out.append((subkey, self._savable_dict(
                        attributes=subattributes,
                        include_none=include_none
                    )))
            elif modified_attributes and key not in modified_attributes:
                continue
            else:
                value = self.raw.get(key)
                if value or include_none:
                    out.append((key, value))
        return dict(out)

    def save(self):
        if not self.id:
            save_method = Panoptes.client().post
        else:
            save_method = Panoptes.client().put

        response, _ = save_method(
            self.url(self.id),
            json={self._api_slug: self._savable_dict(
                modified_attributes=self.modified_attributes
            )},
            etag=self.etag
        )
        self.raw['id'] = response[self._api_slug][0]['id']
        reloaded_project = self.__class__.find(self.id).next()
        self.set_raw(
            reloaded_project.raw,
            reloaded_project.etag
        )

class ResultPaginator(object):
    def __init__(self, object_class, response, etag):
        self.object_class = object_class
        self.set_page(response)
        self.etag = etag

    def __iter__(self):
        return self

    def next(self):
        if self.object_index >= self.object_count:
            if self.next_href:
                response = Panoptes.client().get(self.next_href)
                self.set_page(response)
            else:
                raise StopIteration

        i = self.object_index
        self.object_index += 1
        return self.object_class(self.object_list[i], etag=self.etag)

    def set_page(self, response):
        self.meta = response.get('meta', {})
        self.meta = self.meta.get(self.object_class._api_slug, {})
        self.page = self.meta.get('page', 1)
        self.page_count = self.meta.get('page_count', 1)
        self.next_href = self.meta.get('next_href')
        self.object_list = response.get(self.object_class._api_slug, [])
        self.object_count = len(self.object_list)
        self.object_index = 0

class LinkResolver(object):
    types = {}

    @classmethod
    def register(cls, object_class):
        cls.types[object_class._link_slug] = object_class

    def __init__(self, raw):
        self.raw = raw

    def __getattr__(self, name):
        object_class = LinkResolver.types.get(name)
        linked_object = self.raw[name]
        if type(linked_object) == list:
            return map(lambda o: object_class.find(o).next(), linked_object)
        else:
            return object_class.find(linked_object).next()

class PanoptesAPIException(Exception):
    pass

class ReadOnlyAttributeException(Exception):
    pass