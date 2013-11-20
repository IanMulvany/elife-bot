import boto.swf
import json
import random
import datetime
import calendar
import time

from collections import namedtuple

import activity

import provider.simpleDB as dblib
import provider.templates as templatelib
import provider.ejp as ejplib
import provider.elife as elifelib
import provider.article as articlelib

"""
PublicationEmail activity
"""

class activity_PublicationEmail(activity.activity):
  
  def __init__(self, settings, logger, conn = None, token = None, activity_task = None):
    activity.activity.__init__(self, settings, logger, conn, token, activity_task)

    self.name = "PublicationEmail"
    self.version = "1"
    self.default_task_heartbeat_timeout = 30
    self.default_task_schedule_to_close_timeout = 60*5
    self.default_task_schedule_to_start_timeout = 30
    self.default_task_start_to_close_timeout= 60*5
    self.description = "Queue emails to notify of a new article publication."
    
    # Data provider
    self.db = dblib.SimpleDB(settings)
    
    # Templates provider
    self.templates = templatelib.Templates(settings, self.get_tmp_dir())

    # EJP data provider
    self.ejp = ejplib.EJP(settings, self.get_tmp_dir())
    
    # elife data provider
    self.elife = elifelib.elife(settings)
    
    # article data provider
    self.article = articlelib.article(settings, self.get_tmp_dir())
    
  def do_activity(self, data = None):
    """
    PublicationEmail activity, do the work
    """
    if(self.logger):
      self.logger.info('data: %s' % json.dumps(data, sort_keys=True, indent=4))
    
    # Connect to DB
    db_conn = self.db.connect()
    
    current_time = time.gmtime()
    current_timestamp = calendar.timegm(current_time)
    
    elife_id = data["data"]["elife_id"]
    
    # Prepare email templates
    self.templates.download_email_templates_from_s3()
    if(self.templates.email_templates_warmed is not True):
      if(self.logger):
        self.logger.info('PublicationEmail email templates did not warm successfully')
    else:
      if(self.logger):
        self.logger.info('PublicationEmail email templates warmed')
      
      article = self.article.get_article_data(doi_id = elife_id)
      
      # Get the article published date timestamp
      pub_date_timestamp = None
      date_scheduled_timestamp = 0
      try:
        pub_date_timestamp = self.article.pub_date_timestamp
        date_scheduled_timestamp = pub_date_timestamp
      except:
        pass
      
      # First send author emails
      authors = self.get_authors(doi_id = elife_id)

      for author in authors:

        headers = self.templates.get_author_publication_email_headers(
          author = author,
          article = self.article,
          elife = self.elife,
          format = "html")
        
        # Duplicate email check
        duplicate = self.is_duplicate_email(
          doi_id          = elife_id,
          email_type      = headers["email_type"],
          recipient_email = author.e_mail)
        
        if(duplicate is True):
          if(self.logger):
            self.logger.info('Duplicate email:')
            self.logger.info('Duplicate email: doi_id: %s email_type: %s recipient_email: %s' % (elife_id, headers["email_type"], author.e_mail))
            
        elif(duplicate is False):
          # Queue the email
          self.queue_author_email(
            author  = author,
            headers = headers,
            article = self.article,
            elife   = self.elife,
            doi_id  = elife_id,
            date_scheduled_timestamp = date_scheduled_timestamp,
            format  = "html")
          
      # Second send editor emails
      editors = self.get_editors(doi_id = elife_id)
      
      for editor in editors:
      
        headers = self.templates.get_editor_publication_email_headers(
          editor = editor,
          article = self.article,
          elife = self.elife,
          format = "html")
        
        # Duplicate email check
        duplicate = self.is_duplicate_email(
          doi_id          = elife_id,
          email_type      = headers["email_type"],
          recipient_email = author.e_mail)
        
        if(duplicate is True):
          if(self.logger):
            self.logger.info('Duplicate email: doi_id: %s email_type: %s recipient_email: %s' % (elife_id, headers["email_type"], editor.e_mail))
          
        elif(duplicate is False):
          # Queue the email
          self.queue_editor_email(
            editor  = editor,
            headers = headers,
            article = self.article,
            elife   = self.elife,
            doi_id  = elife_id,
            date_scheduled_timestamp = date_scheduled_timestamp,
            format  = "html")
          
    return True
  
  def queue_author_email(self, author, headers, article, elife, doi_id, date_scheduled_timestamp, format = "html"):
    """
    Format the email body and add it to the live queue
    Only call this to send actual emails!
    """
    body = self.templates.get_author_publication_email_body(
      author  = author,
      article = article,
      elife   = elife,
      format  = format)

    # Add the email to the email queue
    self.db.elife_add_email_to_email_queue(
      recipient_email = author.e_mail,
      sender_email    = headers["sender_email"],
      email_type      = headers["email_type"],
      format          = headers["format"],
      subject         = headers["subject"],
      body            = body,
      doi_id          = doi_id,
      date_scheduled_timestamp = date_scheduled_timestamp)
    
  def queue_editor_email(self, editor, headers, article, elife, doi_id, date_scheduled_timestamp, format = "html"):
    """
    Format the email body and add it to the live queue
    Only call this to send actual emails!
    """
    body = self.templates.get_editor_publication_email_body(
      editor  = editor,
      article = article,
      elife   = elife,
      format  = format)

    # Add the email to the email queue
    self.db.elife_add_email_to_email_queue(
      recipient_email = editor.e_mail,
      sender_email    = headers["sender_email"],
      email_type      = headers["email_type"],
      format          = headers["format"],
      subject         = headers["subject"],
      body            = body,
      doi_id          = doi_id,
      date_scheduled_timestamp = date_scheduled_timestamp)
  
  def is_duplicate_email(self, doi_id, email_type, recipient_email):
    """
    Use the SimpleDB provider to count the number of emails
    in the queue for the particular combination of variables
    to determine whether we should not send an email twice
    Default: return None
      No matching emails: return False
      Is a matching email in the queue: return True
    """
    duplicate = None
    try:
      result_list = self.db.elife_get_email_queue_items(
        query_type = "count",
        doi_id     = doi_id,
        email_type = email_type,
        recipient_email = recipient_email
        )

      count_result = result_list[0]
      count = int(count_result["Count"])
  
      if(count > 0):
        duplicate = True
      elif(count == 0):
        duplicate = False

    except:
      # Do nothing, we will return the default
      pass
    
    return duplicate
                      
  
  def get_authors(self, doi_id = None, corresponding = None, document = None):
    """
    Using the EJP data provider, get the column headings
    and author data, and reassemble into a list of authors
    document is only provided when running tests, otherwise just specify the doi_id
    """
    author_list = []
    (column_headings, authors) = self.ejp.get_authors(doi_id = doi_id, corresponding = corresponding, document = document)
    for author in authors:
      i = 0
      temp = {}
      for value in author:
        heading = column_headings[i]
        temp[heading] = value
        i = i + 1
      # Special: convert the dict to an object for use in templates
      obj = Struct(**temp)
      author_list.append(obj)
      
    return author_list
  
  def get_editors(self, doi_id = None, document = None):
    """
    Using the EJP data provider, get the column headings
    and editor data, and reassemble into a list of editors
    document is only provided when running tests, otherwise just specify the doi_id
    """
    editor_list = []
    (column_headings, editors) = self.ejp.get_editors(doi_id = doi_id, document = document)
    for editor in editors:
      i = 0
      temp = {}
      for value in editor:
        heading = column_headings[i]
        temp[heading] = value
        i = i + 1
      # Special: convert the dict to an object for use in templates
      obj = Struct(**temp)
      editor_list.append(obj)
      
    return editor_list

class Struct(object):
  def __init__(self, **entries):
    self.__dict__.update(entries)

