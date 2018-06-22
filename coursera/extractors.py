"""
This module contains implementation for extractors. Extractors know how
to parse site of MOOC platform and return a list of modules to download.
Usually they do not download heavy content, except when necessary
to parse course syllabus.
"""

import os
import abc
import json
import logging

from .api import CourseraOnDemand, OnDemandCourseMaterialItems
from .define import OPENCOURSE_CONTENT_URL, OPENCOURSE_MEMBERSHIPS
from .cookies import login
from .network import get_page
from .utils import is_debug_run, clean_filename


class PlatformExtractor(object):
    __metaclass__ = abc.ABCMeta

    def get_modules(self):
        """
        Get course modules.
        """
        pass


class CourseraExtractor(PlatformExtractor):
    def __init__(self, session, username, password):
        login(session, username, password)
        self._notebook_downloaded = False
        self._session = session
        self._user_id = self.obtain_user_id()

    def obtain_user_id(self):
        reply = get_page(self._session, OPENCOURSE_MEMBERSHIPS, json=True)
        elements = reply['elements']
        user_id = elements[0]['userId'] if elements else None
        return user_id

    def list_courses(self):
        """
        List enrolled courses.

        @return: List of enrolled courses.
        @rtype: [str]
        """
        course = CourseraOnDemand(session=self._session,
                                  course_id=None,
                                  course_name=None)
        return course.list_courses()

    def get_modules(self, class_name,
                    reverse=False, unrestricted_filenames=False,
                    subtitle_language='en', video_resolution=None,
                    download_quizzes=False, mathjax_cdn_url=None,
                    download_notebooks=False):

        # Fixme: course_name == class_name?

        page = self._get_on_demand_syllabus(class_name)
        error_occurred, modules = self._parse_on_demand_syllabus(
            class_name, page, reverse, unrestricted_filenames,
            subtitle_language, video_resolution,
            download_quizzes, mathjax_cdn_url, download_notebooks)
        return error_occurred, modules

    def _get_on_demand_syllabus(self, class_name):
        """
        Get the on-demand course listing webpage.
        """

        url = OPENCOURSE_CONTENT_URL.format(class_name=class_name, user_id=self._user_id)
        page = get_page(self._session, url)
        logging.info('Downloaded %s (%d bytes)', url, len(page))

        return page

    def _parse_on_demand_syllabus(self, course_name, page, reverse=False,
                                  unrestricted_filenames=False,
                                  subtitle_language='en',
                                  video_resolution=None,
                                  download_quizzes=False,
                                  mathjax_cdn_url=None,
                                  download_notebooks=False
                                  ):
        """
        Parse a Coursera on-demand course listing/syllabus page.

        @return: Tuple of (bool, list), where bool indicates whether
            there was at least on error while parsing syllabus, the list
            is a list of parsed modules.
        @rtype: (bool, list)
        """

        dom = json.loads(page)
        dom = dom['elements'][0]

        logging.info('Parsing syllabus of on-demand course. '
                     'This may take some time, please be patient ...')
        modules = []
        json_modules = dom['weeks']
        course = CourseraOnDemand(session=self._session, course_id=dom['courseId'],
                                  course_name=course_name,
                                  unrestricted_filenames=unrestricted_filenames,
                                  mathjax_cdn_url=mathjax_cdn_url
                                  )
        course._user_id = self._user_id
        ondemand_material_items = OnDemandCourseMaterialItems.create(
            session=self._session, course_name=course_name)

        if is_debug_run():
            with open('%s-syllabus-raw.json' % course_name, 'w') as file_object:
                json.dump(dom, file_object, indent=4)
            with open('%s-course-material-items.json' % course_name, 'w') as file_object:
                json.dump(ondemand_material_items._items, file_object, indent=4)

        error_occurred = False

        for module_idx, module in enumerate(json_modules):
            module_slug = "week_%i" % (module_idx + 1,)
            logging.info('Processing module  %s', module_slug)
            sections = []
            json_sections = module['modules']
            for section in json_sections:
                section_slug = clean_filename(section["name"])
                logging.info('Processing section     %s', section_slug)
                lectures = []
                json_lectures = section['items']

                # Certain modules may be empty-looking programming assignments
                # e.g. in data-structures, algorithms-on-graphs ondemand courses
                if not json_lectures:
                    lesson_id = section['id']
                    lecture = ondemand_material_items.get(lesson_id)
                    if lecture is not None:
                        json_lectures = [lecture]

                for lecture in json_lectures:
                    lecture_slug = os.path.split(lecture['resourcePath'])[-1]
                    typename = lecture['contentSummary']['typeName']

                    logging.info('Processing lecture         %s (%s)',
                                 lecture_slug, typename)
                    # Empty dictionary means there were no data
                    # None means an error occurred
                    links = {}

                    if typename == 'lecture':
                        lecture_video_id = lecture['id']
                        assets = lecture['contentSummary']['definition'].get('assets', [])

                        links = course.extract_links_from_lecture(
                            lecture_video_id, subtitle_language,
                            video_resolution, assets)

                    elif typename == 'supplement':
                        links = course.extract_links_from_supplement(lecture['id'])

                    elif typename == 'phasedPeer':
                        links = course.extract_links_from_peer_assignment(lecture['id'])

                    elif typename in ('gradedProgramming', 'ungradedProgramming'):
                        links = course.extract_links_from_programming(lecture['id'])

                    elif typename == 'quiz':
                        if download_quizzes:
                            links = course.extract_links_from_quiz(lecture['id'])

                    elif typename == 'exam':
                        if download_quizzes:
                            links = course.extract_links_from_exam(lecture['id'])

                    elif typename == 'programming':
                        if download_quizzes:
                            links = course.extract_links_from_programming_immediate_instructions(lecture['id'])

                    elif typename == 'notebook':
                        if download_notebooks and self._notebook_downloaded == False:
                            logging.warning('According to notebooks platform, content will be downloaded first')
                            links = course.extract_links_from_notebook(lecture['id'])
                            self._notebook_downloaded = True

                    else:
                        logging.info(
                            'Unsupported typename "%s" in lecture "%s" (lecture id "%s")',
                            typename, lecture_slug, lecture['id'])
                        continue

                    if links is None:
                        error_occurred = True
                    elif links:
                        lectures.append((lecture_slug, links))

                if lectures:
                    sections.append((section_slug, lectures))

            if sections:
                modules.append((module_slug, sections))

        if modules and reverse:
            modules.reverse()

        # Processing resources section
        json_references= course.extract_references_poll()
        references = []
        if json_references:
            logging.info('Processing resources')
            for json_reference in json_references:
                reference = []
                reference_slug = json_reference['slug']
                logging.info('Processing resource  %s',
                             reference_slug)

                links = course.extract_links_from_reference(json_reference['shortId'])
                if links is None:
                    error_occurred = True
                elif links:
                    reference.append(('', links))

                if reference:
                    references.append((reference_slug, reference))

        if references:
            modules.append(("Resources", references))

        return error_occurred, modules
