"""Contains helper functions for getting data from Illumina BaseSpace."""
import requests
import logging
import os
from django.conf import settings
from ..gcp.storage import upload_file_to_bucket, get_file_in_bucket
from ..private.credentials import BASESPACE

logger = logging.getLogger(__name__)

API_SERVER = "https://api.basespace.illumina.com/"
ACCESS_TOKEN = BASESPACE.get("access_token")
CLIENT_ID = BASESPACE.get("client_id")
CLIENT_SECRET = BASESPACE.get("client_secret")


def build_api_url(api, **kwargs):
    """Builds the URL for BaseSpace API.

    Args:
        api (str): The BaseSpace API, e.g. "v1pre3/files/1863963".
            In the BaseSpace API response, the API for additional data is usually in the "Href" field.
        **kwargs: Additional parameters for the API. They will be encoded in the GET request URL.

    Returns: The full URL for making API request.

    """
    url = "%s%s?access_token=%s" % (
        API_SERVER, api, ACCESS_TOKEN
    )
    for key, val in kwargs.items():
        url += "&%s=%s" % (key, val)
    return url


def get_response(url):
    """Makes HTTP GET request and gets the response content of the BaseSpace API response.
    This function makes the HTTP GET request.
    If the request is successful, the BaseSpace API response is in JSON format.
    Each JSON response contains a "Response" key, for which the value is the actual response content of the API.
    This function returns the value of the "Response" key.

    Args:
        url (str): The HTTP GET request URL.

    Returns: A dictionary containing the the value of the "Response" key in the JSON response.

    """
    r = requests.get(url)
    if r.status_code == 200:
        return r.json().get("Response")
    else:
        return None


def get_integer(dictionary, key):
    """Gets value of a key in the dictionary as a integer.

    Args:
        dictionary (dict): A dictionary.
        key (str): A key in the dictionary.

    Returns: A integer, if the value can be converted to integer. Otherwise None.

    """
    val = dictionary.get(key)
    try:
        return int(val)
    except ValueError:
        return None


def api_response(href, *args, **kwargs):
    """Makes HTTP GET request and gets the response content of the BaseSpace API response.
    This function accepts the API address as input, e.g. "v1pre3/files/1863963".
    If *args are specified, this function will continue to make requests using the api returned in the response.
    For example, if *args = ("Href", "HrefContent"), this function will:
        1. Gets the first response using the API in the href argument.
        2. Gets the "Href" field from the first response and make another request using its value.
        3. Gets the "HrefContent" field from the second response and make another request using its value.


    Args:
        href (str): The BaseSpace API, e.g. "v1pre3/files/1863963".
        *args: Keys for getting APIs for subsequent requests.
        **kwargs: The same parameters will be applied to all api calls.

    Returns: The final BaseSpace API response.

    """
    url = build_api_url(href, **kwargs)
    response = get_response(url)
    for arg in args:
        if response:
            href = response.get(arg)
            if href:
                url = build_api_url(href)
                response = get_response(url)
    return response


def api_collection(href):
    """Makes requests to BaseSpace API and gets all items in a collection.
    The BaseSpace API limits the number of items returned in each request.
    This function makes multiple requests and gets all the items.
    Use this function with caution when there are many items in a collection.

    Args:
        href (str): The BaseSpace API for a collection of items, e.g. "/v1pre3/projects/12345/samples".

    Returns: A list of items (dictionaries) in the collection.

    """
    items = []
    batch_limit = 1024
    total_count = 1
    displayed_count = 0
    offset = 0

    while total_count is not None and displayed_count is not None and offset < total_count:
        url = build_api_url(href, Limit=batch_limit, Offset=offset)
        response = get_response(url)
        if not response:
            return items
        batch = response.get("Items", [])
        if batch:
            items.extend(batch)
        total_count = get_integer(response, "TotalCount")
        displayed_count = get_integer(response, "DisplayedCount")
        offset = offset + displayed_count
    return items


def list_projects():
    """Gets a list of projects.

    Returns: A list of project items (dictionaries, as in the BaseSpace API response).

    """
    href = "v1pre3/users/current/projects"
    return api_collection(href)


def list_samples(project_name):
    """Gets a list of samples for a project.

    Args:
        project_name (str): The name of the project.

    Returns: A list of sample items (dictionaries, as in the BaseSpace API response).

    """
    projects = list_projects()
    href_list = []
    href_samples = None
    samples = []

    for project in projects:
        if project.get("Name") == project_name:
            href = project.get("Href")
            if href:
                href_list.append(href)

    for href in href_list:
        response = api_response(href)
        if response:
            href_samples = response.get("HrefSamples")

        if href_samples:
            samples.extend(api_collection(href_samples))

    return samples


def get_sample(project_name, sample_name):
    """Gets the information of a sample.

    Args:
        project_name (str): The name of the project.
        sample_name (str): The name of the sample (Sample ID).

    Returns: A dictionary containing the sample information.

    """
    samples = list_samples(project_name)
    for sample in samples:
        if sample.get("Name") == sample_name:
            return sample

    return None


def list_files(project_name, sample_name):
    """Gets a list of files for a sample

    Args:
        project_name (str): The name of the project.
        sample_name (str): The name of the sample (Sample ID).

    Returns: A list of file information (dictionaries).

    """
    sample = get_sample(project_name, sample_name)
    if sample:
        href = sample.get("Href")
        api_url = href + "/files"
        return api_collection(api_url)
    return None


def download_file(basespace_file_href, output_filename):
    url = build_api_url(basespace_file_href + "/content")
    response = requests.get(url, stream=True)
    with open(output_filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)


def transfer_file_to_gcloud(gcs_bucket_name, gcs_prefix, file_id=None, file_info_href=None):
    if file_id is not None:
        file_info_href = "v1pre3/files/%s" % file_id
        file_content_href = "v1pre3/files/%s/content" % file_id
    elif file_info_href is not None:
        file_id = file_info_href.strip("/").split("/")[-1]
        file_content_href = "%s/content" % file_info_href
    else:
        logger.error("Either BaseSpace file_id or file_info_href is needed for file transfer.")
        return None
    file_info = api_response(file_info_href)
    logger.debug("Transferring file from: %s" % file_content_href)

    # For FASTQ files, add basespace file ID to filename
    # Each MiSeq run may have multiple FASTQ files with the same name.
    filename = file_info.get("Name")
    if filename.endswith(".fastq.gz"):
        filename = filename.replace(".fastq.gz", "_%s.fastq.gz" % file_id)
    gcs_filename = gcs_prefix + filename
    gs_path = "gs://%s/%s" % (gcs_bucket_name, gcs_filename)

    # Skip if a file exists and have the same size.
    file = get_file_in_bucket(gcs_bucket_name, gcs_filename)
    if file.size != file_info.get("Size"):
        logger.debug("Downloading %s from BaseSpace..." % filename)
        local_filename = os.path.join(settings.TEMP_FILE_FOLDER, filename)
        response = requests.get(build_api_url(file_content_href), stream=True)
        with open(local_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
        logger.debug("Uploading %s to %s..." % (filename, gs_path))
        upload_file_to_bucket(local_filename, gcs_filename, gcs_bucket_name, False)
        if os.path.exists(local_filename):
            os.remove(local_filename)
    else:
        logger.debug("File %s already in Google Cloud Storage: %s" % (filename, gs_path))
    return gs_path
