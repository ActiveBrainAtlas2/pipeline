from lib.TiffSegmentor import TiffSegmentor
import argparse
if __name__ =='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--animal', type=str, help='Animal ID')
    args = parser.parse_args()
    animal = args.animal
    segmentor = TiffSegmentor(animal)
    segmentor.generate_tiff_segments(channel = 1,create_csv = False)
    segmentor.generate_tiff_segments(channel = 3,create_csv = True)
