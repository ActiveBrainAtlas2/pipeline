"""
This file does the following operations:
    1. Convert the thumbnails from TIF to PNG format from the preps/CH1 dir
"""
import argparse
import os
import subprocess

from tqdm import tqdm

from utilities.file_location import FileLocationManager
from utilities.sqlcontroller import SqlController


def make_web_thumbnails(animal):
    """
    This was originally getting the thumbnails from the preps/thumbnail dir but they aren't usuable.
    The ones in the preps/CH1/thumbnail_aligned are much better
    But we need to test if there ane aligned files, if not use the cleaned ones.
    Thumbnails are always created from CH1
    Args:
        animal: the prep id of the animal
        njobs: number of jobs for parallel computing

    Returns:
        nothing
    """
    channel_dir = 'CH1'
    fileLocationManager = FileLocationManager(animal)
    sqlController = SqlController(animal)
    INPUT = os.path.join(fileLocationManager.prep, channel_dir, 'thumbnail_aligned')
    len_files = len(os.listdir(INPUT))
    if len_files < 10:
        INPUT = os.path.join(fileLocationManager.prep, channel_dir, 'thumbnail_cleaned')

    OUTPUT = fileLocationManager.thumbnail_web
    os.makedirs(OUTPUT, exist_ok=True)
    tifs = sqlController.get_sections(animal, 1)

    for i, tif in enumerate(tqdm(tifs)):
        input_path = os.path.join(INPUT, str(i).zfill(3) + '.tif')
        output_path = os.path.join(OUTPUT, os.path.splitext(tif.file_name)[0] + '.png')

        if not os.path.exists(input_path):
            continue

        if os.path.exists(output_path):
            continue

        cmd = "convert {} {}".format(input_path, output_path)
        subprocess.run(cmd, shell=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Work on Animal')
    parser.add_argument('--animal', help='Enter the animal animal', required=True)
    args = parser.parse_args()
    animal = args.animal

    make_web_thumbnails(animal)
