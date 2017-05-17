"""
This module contains implementation for extractors. Extractors know how
to parse site of MOOC platform and return a list of modules to download.
Usually they do not download heavy content, except when necessary
to parse course syllabus.
"""

import abc
import json
import logging

from .api import CourseraOnDemand, OnDemandCourseMaterialItems
from .define import OPENCOURSE_CONTENT_URL, OPENCOURSE_RESOURCES_URL, OPENCOURSE_SINGLE_RESOURCE_URL
from .cookies import login
from .network import get_page
from .utils import is_debug_run


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

        self._session = session

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

    def _get_resources_page(self, course_id):
        url = OPENCOURSE_RESOURCES_URL.format(course_id=course_id)
        page = get_page(self._session, url)
        logging.info('Downloaded resource page %s (%d bytes)', url, len(page))
        return page

    def get_modules(self, class_name,
                    reverse=False, unrestricted_filenames=False,
                    subtitle_language='en', video_resolution=None,
                    download_quizzes=False, mathjax_cdn_addr=None):

        page = self._get_on_demand_syllabus(class_name)
        error_occured, modules = self._parse_on_demand_syllabus(
            page, reverse, unrestricted_filenames,
            subtitle_language, video_resolution,
            download_quizzes, mathjax_cdn_addr)
        return error_occured, modules

    def _get_on_demand_syllabus(self, class_name):
        """
        Get the on-demand course listing webpage.
        """

        url = OPENCOURSE_CONTENT_URL.format(class_name=class_name)
        page = get_page(self._session, url)
        logging.info('Downloaded %s (%d bytes)', url, len(page))

        return page

    def _parse_on_demand_syllabus(self, page, reverse=False,
                                  unrestricted_filenames=False,
                                  subtitle_language='en',
                                  video_resolution=None,
                                  download_quizzes=False,
                                  mathjax_cdn_addr=None
                                  ):
        """
        Parse a Coursera on-demand course listing/syllabus page.

        @return: Tuple of (bool, list), where bool indicates whether
            there was at least on error while parsing syllabus, the list
            is a list of parsed modules.
        @rtype: (bool, list)
        """

        dom = json.loads(page)
        course_name = dom['slug']

        logging.info('Parsing syllabus of on-demand course. '
                     'This may take some time, please be patient ...')
        modules = []
        json_modules = dom['courseMaterial']['elements']
        course = CourseraOnDemand(session=self._session, course_id=dom['id'],
                                  course_name=course_name,
                                  unrestricted_filenames=unrestricted_filenames,
                                  mathjax_cdn_addr=mathjax_cdn_addr
                                  )
        course.obtain_user_id()
        ondemand_material_items = OnDemandCourseMaterialItems.create(
            session=self._session, course_name=course_name)

        if is_debug_run():
            with open('%s-syllabus-raw.json' % course_name, 'w') as file_object:
                json.dump(dom, file_object, indent=4)
            with open('%s-course-material-items.json' % course_name, 'w') as file_object:
                json.dump(ondemand_material_items._items, file_object, indent=4)

        error_occured = False

        for module in json_modules:
            module_slug = module['slug']
            logging.info('Processing module  %s', module_slug)
            sections = []
            json_sections = module['elements']
            for section in json_sections:
                section_slug = section['slug']
                logging.info('Processing section     %s', section_slug)
                lectures = []
                json_lectures = section['elements']

                # Certain modules may be empty-looking programming assignments
                # e.g. in data-structures, algorithms-on-graphs ondemand courses
                if not json_lectures:
                    lesson_id = section['id']
                    lecture = ondemand_material_items.get(lesson_id)
                    if lecture is not None:
                        json_lectures = [lecture]

                for lecture in json_lectures:
                    lecture_slug = lecture['slug']
                    typename = lecture['content']['typeName']

                    logging.info('Processing lecture         %s (%s)',
                                 lecture_slug, typename)
                    # Empty dictionary means there were no data
                    # None means an error occured
                    links = {}

                    if typename == 'lecture':
                        lecture_video_id = lecture['content']['definition']['videoId']
                        assets = lecture['content']['definition'].get('assets', [])

                        links = course.extract_links_from_lecture(
                            lecture_video_id, subtitle_language,
                            video_resolution, assets)

                    elif typename == 'supplement':
                        links = course.extract_links_from_supplement(
                            lecture['id'])

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
                            links = course.extract_links_from_programming_exam(lecture['id'])

                    else:
                        logging.info('Unsupported typename "%s" in lecture "%s"',
                                     typename, lecture_slug)
                        continue

                    if links is None:
                        error_occured = True
                    elif links:
                        lectures.append((lecture_slug, links))

                if lectures:
                    sections.append((section_slug, lectures))

            if sections:
                modules.append((module_slug, sections))

        course_id = dom['id']
        try:
            resources_page = self._get_resources_page(course_id)
        except:
            resources_page = None

        resources_dom = None
        if resources_page:
            resources_dom = json.loads(resources_page)
            if len(resources_dom['elements']) == 0:
                resources_dom = None

        all_resources = None
        if resources_dom:
            all_resources = resources_dom['elements']

        resource_modules = []
        if all_resources:
            for resource in all_resources:
                res_dl = []
                resource_slug = resource['slug']
                logging.info('Processing resource  %s',
                             resource_slug)

                links = course.extract_links_from_resource(resource['shortId'])
                if links is None:
                    error_occured = True
                elif links:
                    res_dl.append(('', links))

                if res_dl:
                    resource_modules.append((resource_slug, res_dl))

        if resources_dom:
            modules.append(("Resources", resource_modules))

        if modules and reverse:
            modules.reverse()

        return error_occured, modules
