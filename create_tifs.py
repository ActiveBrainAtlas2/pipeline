"""
This file does the following operations:
    1. Queries the sections view to get active tifs to be created.
    2. Runs the bfconvert bioformats command to yank the tif out of the czi and place
    it in the correct directory with the correct name
    3. If you  want jp2 files, the bioformats tool will die as the memory requirements are too high.
    To create jp2, first create uncompressed tif files and then use Matlab to create the jp2 files.
    The Matlab script is in registration/tif2jp2.sh
"""
import os
import sys
import argparse
from multiprocessing.pool import Pool

from tqdm import tqdm

from utilities.file_location import FileLocationManager
from utilities.logger import get_logger
from utilities.sqlcontroller import SqlController
from utilities.utilities_process import workershell, workernoshell
from sql_setup import QC_IS_DONE_ON_SLIDES_IN_WEB_ADMIN, CZI_FILES_ARE_CONVERTED_INTO_NUMBERED_TIFS_FOR_CHANNEL_1


def make_tifs(animal, channel, njobs, compression):
    """
    This method will:
        1. Fetch the sections from the database
        2. Yank the tif out of the czi file according to the index and channel with the bioformats tool.
        3. Then updates the database with updated meta information
    Args:
        animal: the prep id of the animal
        channel: the channel of the stack to process
        njobs: number of jobs for parallel computing
        compression: default is no compression so we can create jp2 files for CSHL. The files get
        compressed using LZW when running create_preps.py

    Returns:
        nothing
    """

    logger = get_logger(animal)
    fileLocationManager = FileLocationManager(animal)
    sqlController = SqlController(animal)
    INPUT = fileLocationManager.czi
    OUTPUT = fileLocationManager.tif
    sections = sqlController.get_distinct_section_filenames(animal, channel)

    sqlController.set_task(animal, QC_IS_DONE_ON_SLIDES_IN_WEB_ADMIN)
    sqlController.set_task(animal, CZI_FILES_ARE_CONVERTED_INTO_NUMBERED_TIFS_FOR_CHANNEL_1)

    commands = []
    for section in tqdm(sections):
        input_path = os.path.join(INPUT, section.czi_file)
        output_path = os.path.join(OUTPUT, section.file_name)
        if 'lzw' in compression.lower():
            cmd = ['/usr/local/share/bftools/bfconvert', '-bigtiff', '-compression', 'LZW','-separate', '-series', str(section.scene_index),
                   '-channel', str(section.channel_index),  '-nooverwrite', input_path, output_path]
        elif 'jp' in compression.lower():
            section_jp2 = str(section.file_name).replace('tif', 'jp2')
            output_path = os.path.join(fileLocationManager.jp2, section_jp2)
            cmd = ['/usr/local/share/bftools/bfconvert', '-compression', 'JPEG-2000', '-separate', '-series', str(section.scene_index),
                   '-channel', str(section.channel_index),  '-nooverwrite', input_path, output_path]
        else:
            cmd = ['/usr/local/share/bftools/bfconvert', '-bigtiff', '-separate', '-series', str(section.scene_index),
                   '-channel', str(section.channel_index),  '-nooverwrite', input_path, output_path]

        if not os.path.exists(input_path):
            continue

        if os.path.exists(output_path):
            continue

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        commands.append(cmd)

    with Pool(njobs) as p:
        p.map(workernoshell, commands)

    # Update TIFs' size
    try:
        os.listdir(fileLocationManager.tif)
    except OSError as e:
        logger.error(f'Could not find {fileLocationManager.tif}')
        sys.exit()

    slide_czi_to_tifs = sqlController.get_slide_czi_to_tifs(channel)
    for slide_czi_to_tif in slide_czi_to_tifs:
        tif_path = os.path.join(fileLocationManager.tif, slide_czi_to_tif.file_name)
        if os.path.exists(tif_path):
            slide_czi_to_tif.file_size = os.path.getsize(tif_path)
            sqlController.update_row(slide_czi_to_tif)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Work on Animal')
    parser.add_argument('--animal', help='Enter the animal', required=True)
    parser.add_argument('--channel', help='Enter channel', required=True)
    parser.add_argument('--compression', help='Enter compression LZW or JPG-2000', required=False, default='no')
    parser.add_argument('--njobs', help='How many processes to spawn', default=4, required=False)

    args = parser.parse_args()
    animal = args.animal
    njobs = int(args.njobs)
    channel = int(args.channel)
    compression = args.compression

    logger = get_logger(animal)
    logger.info('Make channel {} tifs'.format(channel))
    make_tifs(animal, channel, njobs, compression)
