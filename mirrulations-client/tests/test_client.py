import os
import json
from mirrcore.path_generator import PathGenerator
import pytest
from pytest import fixture, raises
import requests_mock
from mirrclient.client import NoJobsAvailableException, Client
from mirrclient.client import is_environment_variables_present
from requests.exceptions import Timeout, ReadTimeout
from mirrmock.mock_redis import MockRedisWithStorage

BASE_URL = 'http://work_server:8080'


@fixture(autouse=True)
def mock_env():
    os.environ['WORK_SERVER_HOSTNAME'] = 'work_server'
    os.environ['WORK_SERVER_PORT'] = '8080'
    os.environ['API_KEY'] = 'TESTING_KEY'
    os.environ['ID'] = '-1'


@fixture(name='mock_requests')
def fixture_mock_requests():
    return requests_mock.Mocker()


@fixture(name="path_generator")
def get_path():
    return PathGenerator()


@fixture(autouse=True)
def mock_disk_writing(mocker):
    """
    Mock tests that would be writing to disk
    """
    # patch _write_results and AttachmentSaver.save
    mocker.patch.object(
        Client,
        '_put_results',
        return_value=None
    )
    mocker.patch.object(
        Client,
        'download_single_attachment',
        return_value=None
    )


def test_no_jobs_available_exception_message():
    try:
        raise NoJobsAvailableException
    except NoJobsAvailableException as exception:
        assert str(exception) == "There are no jobs available"


def test_check_no_env_values():
    # Need to delete env variables set by mock_env fixture
    del os.environ['WORK_SERVER_HOSTNAME']
    del os.environ['WORK_SERVER_PORT']
    del os.environ['API_KEY']
    assert is_environment_variables_present() is False


def test_check_no_hostname():
    # Need to delete hostname env variable set by mock_env fixture
    del os.environ['WORK_SERVER_HOSTNAME']
    assert is_environment_variables_present() is False


def test_check_no_server_port():
    # Need to delete server port env variable set by mock_env fixture
    del os.environ['WORK_SERVER_PORT']
    assert is_environment_variables_present() is False


def test_check_no_api_key():
    # Need to delete api key env variable set by mock_env fixture
    del os.environ['API_KEY']
    assert is_environment_variables_present() is False


def test_client_has_no_id():
    # Need to delete id env variable set by mock_env fixture
    del os.environ['ID']
    assert is_environment_variables_present() is False


def test_client_gets_job(mock_requests):
    client = Client(MockRedisWithStorage())
    link = 'https://api.regulations.gov/v4/type/type_id'
    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1', 'url': link, 'job_type': 'attachments',
                  'reg_id': '1', 'agency': 'foo'},
            status_code=200
        )
        job_info = client.get_job()
        assert {'job_id': '1',
                'url': link,
                'job_type': 'attachments',
                'reg_id': '1',
                'agency': 'foo'} == job_info


def test_client_throws_exception_when_no_jobs(mock_requests):
    client = Client(MockRedisWithStorage())
    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'error': 'No jobs available'},
            status_code=403
        )

        with raises(NoJobsAvailableException):
            client.get_job()


def test_api_call_has_api_key(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 'KEY12345'
    with mock_requests:
        mock_requests.get(
            'http://regulations.gov/job',
            json={'data': {'foo': 'bar'}},
            status_code=200
        )
        client.perform_job('http://regulations.gov/job')

        assert '?api_key=KEY12345' in mock_requests.request_history[0].url


def test_client_performs_job(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={'data': {'id': '1', 'type': 'documents',
                           'attributes':
                           {'agencyId': 'NOAA'},
                           'job_type': 'documents'}},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()
        assert client.cache.get_jobs_done()['num_documents_done'] == 1
        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        saved_data = json_data['results']['data']
        assert saved_data['attributes'] == {'agencyId': 'NOAA'}
        assert saved_data['id'] == '1'
        assert saved_data['job_type'] == 'documents'


def test_client_performs_job_with_new_url(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com?include=attachments',
                  'job_type': 'comments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?include=attachments&api_key=1234',
            json={'data': {'id': '1', 'type': 'comments',
                           'attributes':
                           {'agencyId': 'NOAA'},
                           'job_type': 'comments'}},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()

        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        saved_data = json_data['results']['data']
        assert saved_data['attributes'] == {'agencyId': 'NOAA'}
        assert saved_data['id'] == '1'
        assert saved_data['job_type'] == 'comments'


def test_client_returns_403_error_to_server(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )

        regulation_response = {"errors": [{
            "status": "403",
            "title": "The document ID could not be found."}],
            "error": "API limit reached."
        }

        mock_requests.get(
            'http://url.com?api_key=1234',
            json=regulation_response,
            status_code=403
        )

        mock_requests.put(
            'http://work_server:8080/put_results',
            json={'success': 'The job was successfully completed'},
            status_code=200
        )
        client.job_operation()
        response = mock_requests.request_history[-1]
        assert '403' in response.json()


def test_get_job_timesout(mock_requests):
    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job',
            exc=Timeout)

        with pytest.raises(Timeout):
            Client(MockRedisWithStorage()).get_job()


def test_perform_job_timesout(mock_requests):
    with mock_requests:
        fake_url = 'http://regulations.gov/fake/api/call'
        mock_requests.get(
            fake_url,
            exc=ReadTimeout)

        assert Client(MockRedisWithStorage()).perform_job(fake_url) \
            == {"error": "Read Timeout"}


def test_client_returns_400_error_to_server(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )

        regulation_response = {"error": [{
            "status": "400",
            "title": "The document ID could not be found."}]}

        mock_requests.get(
            'http://url.com?api_key=1234',
            json=regulation_response,
            status_code=400
        )

        mock_requests.put(
            'http://work_server:8080/put_results',
            json={'success': 'The job was successfully completed'},
            status_code=200
        )
        client.job_operation()
        response = mock_requests.request_history[-1]
        assert '400' in response.json()


def test_client_returns_500_error_to_server(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )

        regulation_response = {"error": [{
            "status": "500",
            "title": "INTERNAL_SERVER_ERROR",
            "detail": "Incorrect result size: expected 1, actual 2"}]
        }

        mock_requests.get(
            'http://url.com?api_key=1234',
            json=regulation_response,
            status_code=500
        )

        mock_requests.put(
            'http://work_server:8080/put_results',
            json={'success': 'The job was successfully completed'},
            status_code=200
        )
        client.job_operation()
        response = mock_requests.request_history[-1]
        assert '500' in response.json()


def test_client_handles_empty_json(mock_requests, path_generator):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'attachments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={"data": []
                  },
            status_code=200
        )

        mock_requests.get(
            "https://downloads.regulations.gov",
            json={"data": 'foobar'},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()

        mock_requests.put(f'{BASE_URL}/put_results', text='{}')
        client.job_operation()
        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        assert json_data['job_id'] == "1"
        assert json_data['job_type'] == "attachments"
        assert json_data['results'] == {'data': []}
        output_path = path_generator.get_path(json_data['results'])
        assert output_path == "/unknown/unknown.json"


def test_get_output_path_error(path_generator):
    results = {'error': 'error'}
    output_path = path_generator.get_path(results)

    assert output_path == "/unknown/unknown.json"


def test_handles_nonetype_error(mock_requests, path_generator):
    """
    Test for handling of the NoneType Error caused by null fileformats
    """
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://regulations.gov/job',
                  'job_type': 'comments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://regulations.gov/job?api_key=1234',
            json={
                "data": {
                    "id": "agencyID-001-0002",
                    "type": "comments",
                    "attributes": {
                        "agencyId": "agencyID",
                        "docketId": "agencyID-001"
                    }
                },
                "included": [{
                    "attributes": {
                        "fileFormats": None
                    },
                }]
            },
            status_code=200
        )

        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()
        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        assert json_data['job_type'] == "comments"
        results = json_data['results']
        attachment_paths = path_generator.get_attachment_json_paths(results)
        assert attachment_paths == []


def test_success_client_logging(capsys, mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'https://api.regulations.gov/v4/documents/type_id',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'https://api.regulations.gov/v4/documents/type_id?api_key=1234',
            json={'data': {'id': '1', 'type': 'documents',
                           'attributes':
                           {'agencyId': 'NOAA', 'docketId': 'NOAA-0001-0001'},
                           'job_type': 'documents'}},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()
    captured = capsys.readouterr()
    print_data = [
        'Processing job from work server\n',
        'Regulations.gov link: https://www.regulations.gov/document/type_id\n',
        'API URL: https://api.regulations.gov/v4/documents/type_id\n',
        'Performing job\n',
        'Sending Job 1 to Work Server\n',
        'SUCCESS: https://api.regulations.gov/v4/documents/type_id complete\n'
    ]
    assert captured.out == "".join(print_data)


def test_failure_job_results(capsys, mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={"error": 'foobar'},
            status_code=200
        )
        mock_requests.get(
            "https://downloads.regulations.gov",
            json={"error": 'foobar'},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()

        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        assert json_data['results'] == {'error': 'foobar'}
        assert client.cache.get_jobs_done()['num_documents_done'] == 0

        print_data = {
            'Processing job from work server\n'
            'Regulations.gov link: https://www.regulations.gov//url.com\n'
            'API URL: http://url.com\n'
            'Performing job\n'
            'Sending Job 1 to Work Server\n'
            'FAILURE: Error in http://url.com\n'
            'Error: foobar\n'
        }

        captured = capsys.readouterr()
        assert captured.out == "".join(print_data)


# Client Attachments Tests
def test_client_downloads_attachment_results(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'comments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={
                "data": {
                    "id": "FDA-2016-D-2335-1566",
                    "type": "comments",
                    "attributes": {
                        "agencyId": "FDA",
                        "docketId": "FDA-2016-D-2335"
                    }
                },
                "included": [{
                    "attributes": {
                        "fileFormats": [{
                            "fileUrl": "https://fakeurl.gov.pdf"
                        }]
                    }
                }]
            },
            status_code=200
        )
        mock_requests.get(
            "https://fakeurl.gov",
            json={"data": 'foobar'},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')

        client.job_operation()
        job_stat_results = client.cache.get_jobs_done()
        assert job_stat_results['num_comments_done'] == 1
        assert job_stat_results['num_attachments_done'] == 1
        assert job_stat_results['num_pdf_attachments_done'] == 1
        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        assert json_data['job_id'] == "1"
        assert json_data['job_type'] == "comments"


def test_handles_empty_attachment_list(mock_requests):
    """
    Test that handles empty attachment list from comments json being:
    {
        "relationships" : {
                "attachments" : {
                    "data" : [ ]}
                    }
    }
    """
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://regulations.gov/job',
                  'job_type': 'comments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://regulations.gov/job?api_key=1234',
            json={
                "data": {
                    "id": "agencyID-001-0002",
                    "type": "comments",
                    "attributes": {
                        "agencyId": "agencyID",
                        "docketId": "agencyID-001"
                    }
                },
                "relationships": {
                    "attachments": {
                        "data": []
                    }
                }
            },
            status_code=200
        )

        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()
        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        results = json_data['results']
        assert json_data['job_type'] == "comments"
        assert client.does_comment_have_attachment(results) is False


def test_success_attachment_logging(capsys, mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'comments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={
                "data": {
                    "id": "agencyID-001-0002",
                    "type": "comments",
                    "attributes": {
                        "agencyId": "agencyID",
                        "docketId": "agencyID-001"
                    }
                },
                "included": [{
                    "attributes": {
                        "fileFormats": [{
                            "fileUrl": "https://downloads.regulations.gov"
                        }]
                    }
                }]
            },
            status_code=200
        )

        mock_requests.get(
            "https://downloads.regulations.gov",
            json={"data": 'foobar'},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()

        print_data = {
            'Processing job from work server\n'
            'Regulations.gov link: https://www.regulations.gov//url.com\n'
            'API URL: http://url.com\n'
            'Performing job\n'
            'Sending Job 1 to Work Server\n'
            'Found 1 attachment(s) for Comment - agencyID-001-0002\n'
            'Downloaded 1/1 attachment(s) for Comment - agencyID-001-0002\n'
            'SUCCESS: http://url.com complete\n'
        }

        captured = capsys.readouterr()
        assert captured.out == "".join(print_data)


def test_success_no_attachment_logging(capsys, mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'attachments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={"data": []},
            status_code=200
        )

        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()

        print_data = {
            'Processing job from work server\n'
            'Regulations.gov link: https://www.regulations.gov//url.com\n'
            'API URL: http://url.com\n'
            'Performing job\n'
            'Sending Job 1 to Work Server\n'
            'SUCCESS: http://url.com complete\n'
        }

        captured = capsys.readouterr()
        assert captured.out == "".join(print_data)


def test_failure_attachment_job_results(capsys, mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'comments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={
                "data": {
                    "id": "agencyID-001-0002",
                    "type": "comments",
                    "attributes": {
                        "agencyId": "agencyID",
                        "docketId": "agencyID-001"
                    }
                },
                "included": [{
                    "attributes": {
                        "fileFormats": [{
                            "fileUrl": "https://downloads.regulations.gov"
                        }]
                    }
                }]
            },
            status_code=200
        )

        mock_requests.get(
            "https://downloads.regulations.gov",
            json={"data": 'foobar'},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()

        print_data = {
            'Processing job from work server\n'
            'Regulations.gov link: https://www.regulations.gov//url.com\n'
            'API URL: http://url.com\n'
            'Performing job\n'
            'Sending Job 1 to Work Server\n'
            'Found 1 attachment(s) for Comment - agencyID-001-0002\n'
            'Downloaded 1/1 attachment(s) for Comment - agencyID-001-0002\n'
            'SUCCESS: http://url.com complete\n'
        }

        captured = capsys.readouterr()
        assert captured.out == "".join(print_data)


def test_two_attachments_in_comment(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://url.com',
                  'job_type': 'comments',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://url.com?api_key=1234',
            json={
                "data": {
                    "id": "agencyID-001-0002",
                    "type": "comments",
                    "attributes": {
                        "agencyId": "agencyID",
                        "docketId": "agencyID-001"
                    }
                },
                "included": [{
                    "attributes": {
                        "fileFormats": [{
                            "fileUrl": "https://downloads.regulations.gov/.pdf"
                        }, {
                            "fileUrl": "https://downloads.regulations.gov/.doc"
                        }]
                    }
                }]
            },
            status_code=200
        )

        mock_requests.get(
            "https://downloads.regulations.gov",
            json={"data": 'foobar'},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()
        results = client.cache.get_jobs_done()
        assert results['num_comments_done'] == 1
        assert results['num_attachments_done'] == 2
        assert results['num_pdf_attachments_done'] == 1


def test_add_attachment_information_to_data():
    data = {}
    path = '/USTR/docket.json'
    filename = "docket.json"
    client = Client(MockRedisWithStorage())
    data = client.add_attachment_information_to_data(data, path, filename)
    assert data['job_type'] == 'attachments'
    assert data['attachment_path'] == '/data/data/USTR/docket.json'
    assert data['attachment_filename'] == 'docket.json'


def test_download_htm(capsys, mocker, mock_requests):
    mocker.patch('mirrclient.saver.Saver.make_path', return_value=None)
    mocker.patch('mirrclient.saver.Saver.save_attachment', return_value=None)

    client = Client(MockRedisWithStorage())

    pdf = "https://downloads.regulations.gov/USTR/content.pdf"
    htm = "https://downloads.regulations.gov/USTR/content.htm"
    htm_json = {
            "data": {
                "attributes": {
                    "fileFormats": [{
                        "fileUrl": pdf,
                        "format": "pdf",
                        "size": 182010
                        }, {
                        "fileUrl": htm,
                        "format": "htm",
                        "size": 9709
                        }
                    ]
                }
            }
        }

    with mock_requests:
        mock_requests.get(
            htm,
            json={"data": 'foobar'},
            status_code=200
        )

        client.download_htm(htm_json)
        captured = capsys.readouterr().out
        assert f"SAVED document HTM - {htm} to path:" in captured


def test_downloading_htm_send_job(capsys, mock_requests, mocker):
    mocker.patch('mirrclient.saver.Saver.make_path', return_value=None)
    mocker.patch('mirrclient.saver.Saver.save_attachment', return_value=None)
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'https://api.regulations.gov/v4/documents/type_id',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'https://api.regulations.gov/v4/documents/type_id?api_key=1234',
            json={'data': {'id': '1', 'type': 'documents',
                           'attributes':
                           {'agencyId': 'NOAA', 'docketId': 'NOAA-0001-0001',
                            "fileFormats": [{
                               "fileUrl": ("https://downloads.regulations."
                                            "gov/USTR-2015-0010-0001/"
                                            "content.htm"),
                               "format": "htm",
                               "size": 9709
                            }]},
                           'job_type': 'documents'}},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        mock_requests.get('https://downloads.regulations.gov/'
                          'USTR-2015-0010-0001/content.htm')
        client.job_operation()
    captured = capsys.readouterr()
    print_data = [
        'Processing job from work server\n',
        'Regulations.gov link: https://www.regulations.gov/document/type_id\n',
        'API URL: https://api.regulations.gov/v4/documents/type_id\n',
        'Performing job\n',
        'Sending Job 1 to Work Server\n',
        ('SAVED document HTM '
            '- https://downloads.regulations.gov/USTR-2015-0010-0001/'
            'content.htm to path:  '
            '/NOAA/NOAA-0001-0001/text-NOAA-0001-0001/documents/'
            '1_content.htm\n'),
        'SUCCESS: https://api.regulations.gov/v4/documents/type_id complete\n'
    ]
    assert captured.out == "".join(print_data)


def test_downloading_docket(mock_requests):
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'http://regulations.gov/job',
                  'job_type': 'dockets',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'http://regulations.gov/job?api_key=1234',
            json={
                "data": {
                    "id": "agencyID-001-0002",
                    "type": "dockets"
                },
            },
            status_code=200
        )

        mock_requests.put('http://work_server:8080/put_results', text='{}')
        client.job_operation()
        assert client.cache.get_jobs_done()['num_dockets_done'] == 1
        put_request = mock_requests.request_history[2]
        json_data = json.loads(put_request.json())
        assert json_data['job_type'] == "dockets"
        results = json_data['results']['data']
        assert results['type'] == 'dockets'


def test_download_no_htm_send_job(capsys, mock_requests, mocker):
    mocker.patch('mirrclient.saver.Saver.make_path', return_value=None)
    mocker.patch('mirrclient.saver.Saver.save_attachment', return_value=None)
    client = Client(MockRedisWithStorage())
    client.api_key = 1234

    with mock_requests:
        mock_requests.get(
            'http://work_server:8080/get_job?client_id=-1',
            json={'job_id': '1',
                  'url': 'https://api.regulations.gov/v4/documents/type_id',
                  'job_type': 'documents',
                  'reg_id': '1',
                  'agency': 'foo'},
            status_code=200
        )
        mock_requests.get(
            'https://api.regulations.gov/v4/documents/type_id?api_key=1234',
            json={'data': {'id': '1', 'type': 'documents',
                           'attributes':
                           {'agencyId': 'NOAA', 'docketId': 'NOAA-0001-0001',
                            "fileFormats": None},
                           'job_type': 'documents'}},
            status_code=200
        )
        mock_requests.put('http://work_server:8080/put_results', text='{}')
        mock_requests.get('https://downloads.regulations.gov/'
                          'USTR-2015-0010-0001/content.htm')
        client.job_operation()
    captured = capsys.readouterr()
    print_data = [
        'Processing job from work server\n',
        'Regulations.gov link: https://www.regulations.gov/document/type_id\n',
        'API URL: https://api.regulations.gov/v4/documents/type_id\n',
        'Performing job\n',
        'Sending Job 1 to Work Server\n',
        'SUCCESS: https://api.regulations.gov/v4/documents/type_id complete\n'
    ]
    assert captured.out == "".join(print_data)
