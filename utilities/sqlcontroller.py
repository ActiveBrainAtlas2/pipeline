"""
This is the base sql class. It is mostly used per animal, so the init function
needs an animal passed to the constructor
It also needs for the animal, histology and scan run tables to be
filled out for each animal to use
"""
#import logging
#import traceback
#import transaction
###from logger import Log
import json
import pandas as pd
from collections import OrderedDict

from sqlalchemy import func
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import AmbiguousForeignKeysError
from sqlalchemy.exc import ArgumentError
from sqlalchemy.exc import CircularDependencyError

from model.animal import Animal
from model.histology import Histology
from model.scan_run import ScanRun
from model.section import Section
from model.slide import Slide
from model.slide_czi_to_tif import SlideCziTif
from model.structure import Structure
from model.center_of_mass import CenterOfMass
from model.task import Task, ProgressLookup
from model.urlModel import UrlModel
from sql_setup import session
from datetime import datetime


class SqlController(object):
    """ Create a class for processing the pipeline,
    """

    def __init__(self, animal):
        """ setup the attributes for the SlidesProcessor class
            Args:
                animal: object of animal to process
                session: sql session to run queries
        """
        self.session = session
        self.stack_metadata = {}
        self.all_stacks = []
        self.animal = session.query(Animal).filter(Animal.prep_id == animal).one()
        try:
            self.histology = session.query(Histology).filter(Histology.prep_id == animal).one()
        except NoResultFound:
            print(f'No histology for {animal}')
        try:
            self.scan_run = session.query(ScanRun).filter(ScanRun.prep_id == animal).order_by(ScanRun.id.desc()).one()
        except NoResultFound:
            print(f'No scan run for {animal}')
        self.slides = None
        self.tifs = None
        self.valid_sections = OrderedDict()
        # fill up the metadata_cache variable

    def get_section(self, id):
        """
        The sections table is a view and it is already filtered by active and file_status = 'good'
        This qeury returns a single section by id.
        Args:
            id: integer primary key

        Returns: one section
        """
        return self.session.query(Section).filter(Section.id == id).one()

    def get_sections(self, animal, channel):
        """
        The sections table is a view and it is already filtered by active and file_status = 'good'
        The ordering is important. This needs to come from the histology table.
        Args:
            animal: the animal to query
            channel: 1 or 2 or 3.

        Returns: list of sections in order

        """
        orderby = self.histology.side_sectioned_first

        if orderby == 'DESC':
            sections = self.session.query(Section).filter(Section.prep_id == animal)\
                .filter(Section.channel == channel)\
                .order_by(Section.slide_physical_id.desc())\
                .order_by(Section.scene_number.desc()).all()
        else:
            sections = self.session.query(Section).filter(Section.prep_id == animal)\
                .filter(Section.channel == channel)\
                .order_by(Section.slide_physical_id.asc())\
                .order_by(Section.scene_number.asc()).all()

        return sections

    def get_distinct_section_filenames(self, animal, channel):
        """
        Very similar to the get_sections query but this will return a list of
        distinct file names. Since some of the scenes get duplicated in the QA process,
        we need to get the tifs without duplicates. The duplicates will then get replicated
        with the get_sections method. The order doesn't matter here.
        Args:
            animal: the animal to query
            channel: 1 or 2 or 3.

        Returns: list of sections with distinct file names

        """
        sections = self.session.query(Section.czi_file, Section.file_name, Section.scene_index, Section.channel_index).distinct()\
            .filter(Section.prep_id == animal).filter(
            Section.channel == channel) \

        return sections

    def get_slide_czi_to_tifs(self, channel):
        slides = self.session.query(Slide).filter(Slide.scan_run_id == self.scan_run.id)\
            .filter(Slide.slide_status == 'Good').all()
        slide_czi_to_tifs = self.session.query(SlideCziTif).filter(SlideCziTif.channel == channel)\
            .filter(SlideCziTif.slide_id.in_([slide.id for slide in slides]))\
            .filter(SlideCziTif.active == 1).all()

        return slide_czi_to_tifs

    def update_row(self, row):
        self.session.merge(row)
        self.session.commit()

    def get_sections_numbers(self, animal):
        sections = self.session.query(Section).filter(Section.prep_id == animal).filter(Section.channel == 1).all()

        section_numbers = []
        for i, r in enumerate(sections):
            section_numbers.append(i)

        return section_numbers

    def get_sections_dict(self, animal):
        sections = self.session.query(Section).filter(Section.prep_id == animal).filter(Section.channel == 1).all()

        sections_dict = {}
        for i, r in enumerate(sections):
            sections_dict[i] = str(i).zfill(3) + 'tif'

        return sections_dict

    def get_structure(self, abbrv):
        """
        Returns a structure
        This search has to be case sensitive!
        :param abbrv: the abbreviation of the structure
        :return: structure object
        """

        return self.session.query(Structure).filter(Structure.abbreviation == func.binary(abbrv)).one()

    def get_structure_color_rgb(self, abbrv):
        """
        Returns a color code in RGB format like (1,2,3)
        This search has to be case sensitive!
        :param abbrv: the abbreviation of the structure
        :return: tuple of rgb
        """
        row = self.session.query(Structure).filter(Structure.abbreviation == func.binary(abbrv)).one()
        hexa = row.hexadecimal
        h = hexa.lstrip('#')
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    def get_structures(self):
        return self.session.query(Structure).filter(Structure.active.is_(True)).all()

    def get_structures_dict(self):
        rows = self.session.query(Structure).filter(Structure.active.is_(True)).all()
        structures_dict = {}
        for structure in rows:
            structures_dict[structure.abbreviation] = [structure.description, structure.color]

        return structures_dict

    def get_sided_structures(self):
        """
        Not sure when/if this is needed, but will only return sided structures
        :return: list of structures that are not singules
        """
        rows = self.session.query(Structure).filter(Structure.active.is_(True)).all()
        structures = []
        for structure in rows:
            if structure.abbreviation.contains('_'):
                structures.append(structure.abbreviation)

        return sorted(structures)

    def get_section_count(self, animal):
        try:
            count = self.session.query(Section).filter(Section.prep_id == animal).filter(Section.channel == 1).count()
        except:
            count = 666
        return count

    def get_current_task(self, animal):
        step = None
        try:
            lookup_id = self.session.query(func.max(Task.lookup_id)).filter(Task.prep_id == animal) \
                .filter(Task.completed.is_(True)).scalar()
        except NoResultFound as nrf:
            print('No results for {} error: {}'.format(animal, nrf))
            return step

        try:
            lookup = self.session.query(ProgressLookup).filter(ProgressLookup.id == lookup_id).one()
        except NoResultFound as nrf:
            print('Bad lookup code for {} error: {}'.format(lookup_id, nrf))
            return step

        return lookup.description

    def set_task(self, animal, lookup_id):
        """
        Look up the lookup up from the step. Check if the animal already exists,
        if not, insert, otherwise, update
        Args:
            animal: string of the animal you are working on
            lookup_id: current lookup ID
        Returns:
            nothing, just merges
        """
        try:
            lookup = self.session.query(ProgressLookup) \
                .filter(ProgressLookup.id == lookup_id) \
                .limit(1).one()
        except NoResultFound:
            print('No lookup for {} so we will enter one.'.format(lookup_id))
        try:
            task = self.session.query(Task).filter(Task.lookup_id == lookup.id) \
                .filter(Task.prep_id == animal).one()
        except NoResultFound:
            print('No step for {}, so creating new task.'.format(lookup_id))
            task = Task(animal, lookup.id, True)

        try:
            self.session.merge(task)
            self.session.commit()
        except:
            print('Bad lookup code for {}'.format(lookup.id))
            self.session.rollback()


    def add_center_of_mass(self, abbreviation, animal, x, y, section):
        """
        Look up the structure id from the structure.
        Args:
            structure: abbreviation with the _L or _R ending
            animal: prep_id
            x=float of x coordinate
            y=float of y coordinate
            section = int of z/section coordinate
        Returns:
            nothing, just merges
        try:
            structure = self.session.query(Structure) \
                .filter(Structure.abbreviation == func.binary(abbreviation)).one()
        except NoResultFound:
            print(f'No structure for {abbreviation}')
        """

        structure = self.get_structure(abbreviation)
        id = structure.id

        com = CenterOfMass(prep_id=animal, structure_id=id, x=x, y=y, section=section,
                           created=datetime.now, active=True)


        try:
            self.session.add(com)
            self.session.commit()
        except:
            print(f'No merge for {abbreviation}')
            self.session.rollback()
            raise
        finally:
            # close the Session.  This will expunge any remaining
            # objects as well as reset any existing SessionTransaction
            # state.  Neither of these steps are usually essential.
            # However, if the commit() or rollback() itself experienced
            # an unanticipated internal failure (such as due to a mis-behaved
            # user-defined event handler), .close() will ensure that
            # invalid state is removed.
            self.session.close()




    def get_centers_dict(self, prep_id):
        rows = self.session.query(CenterOfMass).filter(CenterOfMass.active.is_(True)).filter(CenterOfMass.prep_id==prep_id).all()
        row_dict = {}
        for row in rows:
            structure = row.structure.abbreviation
            row_dict[structure] = [row.x, row.y, row.section]

        return row_dict



    def get_point_dataframe(self, id):
        """

        :param id: primary key from the url. Look at:
         https://activebrainatlas.ucsd.edu/activebrainatlas/admin/neuroglancer/points/164/change/
         for example use 164 for the primary key
         to get the ID
        :return: a pandas dataframe
        """

        try:
            urlModel = self.session.query(UrlModel).filter(UrlModel.id == id).one()
        except NoResultFound as nrf:
            print('Bad ID for {} error: {}'.format(id, nrf))
            return

        result = None
        dfs = []
        if urlModel.url is not None:
            json_txt = json.loads(urlModel.url)
            layers = json_txt['layers']
            for l in layers:
                if 'annotations' in l:
                    name = l['name']
                    annotation = l['annotations']
                    d = [row['point'] for row in annotation]
                    df = pd.DataFrame(d, columns=['X', 'Y', 'Section'])
                    df['X'] = df['X'].astype(int)
                    df['Y'] = df['Y'].astype(int)
                    df['Section'] = df['Section'].astype(int)
                    df['Layer'] = name
                    df = df[['Layer', 'X', 'Y', 'Section']]
                    dfs.append(df)
            if len(dfs) == 0:
                result = None
            elif len(dfs) == 1:
                result = dfs[0]
            else:
                result = pd.concat(dfs)

        return result


"""
    class SQLAlchemyHandler(logging.Handler):
        # A very basic logger that commits a LogRecord to the SQL Db
        def emit(self, record):
            trace = None
            exc = record.__dict__['exc_info']
            if exc:
                trace = traceback.format_exc()
            log = Log(
                logger=record.__dict__['name'],
                level=record.__dict__['levelname'],
                trace=trace,
                msg=record.__dict__['msg'],)
            self.session.add(log)
            transaction.commit()
"""
