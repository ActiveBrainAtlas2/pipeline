"""
This class is used to run the entire preprocessing pipeline - 
from CZI files to a pyramid of tiles that can be viewed in neuroglancer.

Args are animal, channel, and downsample. With animal being
the only required argument.
All imports are listed by the order in which they are used in the 
"""

import os
import sys
import shutil
import threading
from timeit import default_timer as timer

from image_manipulation.filelocation_manager import FileLocationManager
from image_manipulation.meta_manager import MetaUtilities
from image_manipulation.prep_manager import PrepCreater
from image_manipulation.precomputed_manager import NgPrecomputedMaker
from image_manipulation.progress_manager import ProgressLookup
from image_manipulation.tiff_extractor_manager import TiffExtractor
from image_manipulation.file_logger import FileLogger
from image_manipulation.parallel_manager import ParallelManager
from image_manipulation.normalizer_manager import Normalizer
from image_manipulation.mask_manager import MaskManager
from image_manipulation.image_cleaner import ImageCleaner
from image_manipulation.histogram_maker import HistogramMaker
from image_manipulation.elastix_manager import ElastixManager
from controller.sql_controller import SqlController
from utilities.utilities_process import get_hostname


class Pipeline(
    MetaUtilities,
    TiffExtractor,
    PrepCreater,
    ParallelManager,
    Normalizer,
    MaskManager,
    ImageCleaner,
    HistogramMaker,
    ElastixManager,
    NgPrecomputedMaker,
    FileLogger
):
    """
    This is the main class that handles the preprocessing pipeline responsible for converting Zeiss microscopy images (.czi) into neuroglancer
    viewable formats.  The Zeiss module can be swapped out to make the pipeline compatible with other microscopy setups
    """
    TASK_CREATING_META = "Yanking meta data from CZI files"
    TASK_CREATING_WEB_IMAGES = "Creating web friendly PNG images"
    TASK_EXTRACTING_TIFFS = "Extracting TIFFs"
    TASK_APPLYING_QC = "Applying QC"
    TASK_APPLYING_NORMALIZATION = "Creating normalization"
    TASK_CREATING_MASKS = "Creating masks"
    TASK_APPLYING_MASKS = "Applying masks"
    TASK_CREATING_CLEANED_IMAGES = "Creating cleaned image"
    TASK_CREATING_HISTOGRAMS =  "Making histogram"
    TASK_CREATING_COMBINED_HISTOGRAM = "Making combined histogram"
    TASK_CREATING_ELASTIX_TRANSFORM = "Creating elastix transform"
    TASK_CREATING_ELASTIX_METRICS = "Creating elastix  metrics"
    TASK_NEUROGLANCER_SINGLE = "Neuroglancer1 single"
    TASK_NEUROGLANCER_PYRAMID = "Neuroglancer2 pyramid"

    def __init__(self, animal, channel, downsample, data_path, tg, debug):
        """Setting up the pipeline and the processing configurations
        Here is how the Class is instantiated:
            pipeline = Pipeline(animal, channel, downsample, data_path, tg, debug)

           The pipeline performst the following steps:
           1. extracting the images from the microscopy formats (eg czi) to tiff format
           2. Prepare thumbnails of images for quality control
           3. clean the images
           4. align the images
           5. convert to Seung lab neuroglancer cloudvolume format

           step 3 and 4 are first performed on downsampled images, and the image masks(for step 3) and the within stack alignments(for step 4) are
           upsampled for use in the full resolution images

        Args:
            animal (str): Animal Id
            channel (int, optional): channel number.  This tells the program which channel to work on and which channel to extract from the czis. Defaults to 1.
            downsample (bool, optional): Determine if we are working on the full resolution or downsampled version. Defaults to True.
            data_path (str, optional): path to where the images and intermediate steps are stored. Defaults to '/net/birdstore/Active_Atlas_Data/data_root'.
            debug (bool, optional): determine if we are in debug mode.  This is used for development purposes. Defaults to False. (forces processing on single core)
        """
        self.animal = animal
        self.channel = channel
        self.downsample = downsample
        self.debug = debug
        self.fileLocationManager = FileLocationManager(animal, data_path=data_path)
        self.sqlController = SqlController(animal)
        self.hostname = get_hostname()
        self.tg = tg
        self.progress_lookup = ProgressLookup()
        self.check_programs()
        self.section_count = self.sqlController.get_section_count(self.animal)
        super().__init__(self.fileLocationManager.get_logdir())


    @staticmethod
    def check_programs():
        """
        Make sure the necessary tools are installed on the machine and configures the memory of involving tools to work with
        big images.
        Some tools we use are based on java so we adjust the java heap size limit to 10 GB.  This is big enough for our purpose but should
        be increased accordingly if your images are bigger
        If the check failed, check the workernoshell.err.log in your project directory for more information
        """
        start_time = timer()
        
        error = ""
        if not os.path.exists("/usr/bin/identify"):
            error += "\nImagemagick is not installed"

        if len(error) > 0:
            print(error)
            sys.exit()
        end_time = timer()
        total_elapsed_time = end_time - start_time
        print(f"Check programs took {round(total_elapsed_time,1)} seconds")

    def run_program_and_time(self, function, function_name):
        """utility to run a specific function and time it

        Args:
            function (function): funtion to run
            function_name (str): name of the function used to report timing result
        """
        print(function_name, end="")
        start_time = timer()
        self.logevent(f"START  {str(function_name)}, downsample: {str(self.downsample)}")

        function()  # RUN FUNCTION

        end_time = timer()
        total_elapsed_time = round((end_time - start_time),2)
        print(f" took {total_elapsed_time} seconds")
        sep = "*" * 40 + "\n"
        self.logevent(f"{function_name} took {total_elapsed_time} seconds\n{sep}")

    def qc_cleanup(self):
        """Post QC to clean up filesystem prior to re-running mask edits"""

        def background_del(org_path):
            try:
                basename = os.path.basename(os.path.normpath(org_path))
                new_path = os.path.join(org_path, "..", "." + str(basename))
                if os.path.exists(basename):
                    os.rename(org_path, new_path)
                    threading.Thread(target=lambda: shutil.rmtree(new_path)).start()
                else:
                    print(f"FOLDER ALREADY DELETED: {basename}")
            except OSError as e:
                print(f"FOLDER ALREADY DELETED: {new_path} {e}")

        sep = "*" * 40 + "\n"
        msg = f"DELETE MASKED FILES FROM {self.fileLocationManager.thumbnail_masked}"
        self.logevent(f"{msg} \n{sep}")
        background_del(self.fileLocationManager.thumbnail_masked)

    def align_cleanup(self):
        """
        THIS STEP IS RE-RUN IMAGE ALIGNMENT:
        DELETE FOLDERS:
        DELETE DB ENTRIES:
        """

        def background_del(org_path):
            try:
                basename = os.path.basename(os.path.normpath(org_path))
                new_path = os.path.join(org_path, "..", "." + str(basename))
                if os.path.exists(basename):
                    os.rename(org_path, new_path)
                    threading.Thread(target=lambda: shutil.rmtree(new_path)).start()
                else:
                    print(f"FOLDER ALREADY DELETED: {basename}")
            except OSError as e:
                print(f"FOLDER ALREADY DELETED: {new_path} {e}")

        sep = "*" * 40 + "\n"
        thumbnail_aligned_dir = self.fileLocationManager.get_thumbnail_aligned()
        msg = f"DELETE ALIGNED THUMBNAILS FILES FROM {thumbnail_aligned_dir}"
        self.logevent(f"{msg} \n{sep}")
        background_del(thumbnail_aligned_dir)

        thumbnail_cleaned_dir = self.fileLocationManager.get_thumbnail_cleaned()
        msg = f"DELETE CLEANED THUMBNAILS FILES FROM {thumbnail_cleaned_dir}"
        self.logevent(f"{msg} \n{sep}")
        background_del(thumbnail_cleaned_dir)
