import activity
import re
import json
import time
from os.path import isfile, join
from os import listdir, mkdir
from os import path
from boto.s3.key import Key
from boto.s3.connection import S3Connection
from S3utility.s3_notification_info import S3NotificationInfo
from provider.execution_context import Session
from zipfile import ZipFile

"""
ExpandArticle.py activity
"""

class activity_ExpandArticle(activity.activity):
    def __init__(self, settings, logger, conn=None, token=None, activity_task=None):
        activity.activity.__init__(self, settings, logger, conn, token, activity_task)

        self.name = "ExpandArticle"
        self.version = "1"
        self.default_task_heartbeat_timeout = 30
        self.default_task_schedule_to_close_timeout = 60 * 5
        self.default_task_schedule_to_start_timeout = 30
        self.default_task_start_to_close_timeout = 60 * 5
        self.description = "Expands an article ZIP to an expanded folder, renaming as required"
        self.logger = logger

    def do_activity(self, data=None):
        """
        Do the work
        """
        if self.logger:
            self.logger.info('data: %s' % json.dumps(data, sort_keys=True, indent=4))
        info = S3NotificationInfo.from_dict(data)

        # set up required connections
        conn = S3Connection(self.settings.aws_access_key_id, self.settings.aws_secret_access_key)
        source_bucket = conn.get_bucket(info.bucket_name)
        dest_bucket = conn.get_bucket(self.settings.expanded_article_bucket)
        session = Session(self.settings)

        # set up logging
        if self.logger:
            self.logger.info("Expanding file %s" % info.file_name)

        # extract any version and updated date information from the filename

        version = None
        # zip name contains version information for previously archived zip files
        m = re.search(ur'-v([0-9]*?)[\.|-]', info.file_name)
        if m is not None:
            version = m.group(1)
        if version is None:
            # TODO : get next version from API
            version = 0
        # store version for other activities in this workflow execution
        session.store_value(self.get_workflowId(), 'version', version)
        # TODO : extract and store updated date if supplied

        # download zip to temp folder
        tmp = self.get_tmp_dir()
        key = Key(source_bucket)
        key.key = info.file_name
        local_zip_file = self.open_file_from_tmp_dir(info.file_name, mode='w')
        key.get_contents_to_file(local_zip_file)
        local_zip_file.close()

        # TODO : generate final name
        folder_name = info.file_name.replace(".zip", "") + str(time.time())

        # extract zip contents
        content_folder = path.join(tmp, folder_name)
        mkdir(content_folder)
        with ZipFile(path.join(tmp, info.file_name)) as zf:
            zf.extractall(content_folder)

        # TODO : rename files

        # TODO : edit xml and rename references

        upload_filenames = []
        for f in listdir(content_folder):
            if isfile(join(content_folder, f)) and f[0] != '.' and not f[0] == '_':
                upload_filenames.append(f)

        for filename in upload_filenames:
            source_path = path.join(content_folder, filename)
            dest_path = path.join(folder_name, filename)
            k = Key(dest_bucket)
            k.key = dest_path
            k.set_contents_from_filename(source_path)

        session.store_value(self.get_workflowId(), 'expanded_folder', folder_name)

        return True

        # conn = S3Connection(self.settings.aws_access_key_id, self.settings.aws_secret_access_key)
        # bucket = conn.get_bucket(info.bucket_name)
        # key = Key(bucket)
        # key.key = info.file_name
        # xml = key.get_contents_as_string()
        # if self.logger:
        #     self.logger.info("Downloaded contents of file %s" % info.file_name)
        #
        # json_output = jats_scraper.scrape(xml)
        #
        # if self.logger:
        #     self.logger.info("Scraped file %s" % info.file_name)
        #
        # # TODO (see note above about utility class for S3 work)
        # output_name = info.file_name.replace('.xml', '.json')
        # destination = conn.get_bucket(self.settings.jr_S3_NAF_bucket)
        # destination_key = Key(destination)
        # destination_key.key = output_name
        # destination_key.set_contents_from_string(json_output)
        #
        # if self.logger:
        #     self.logger.info("Uploaded key %s to %s" % (output_name, self.settings.jr_S3_NAF_bucket))

