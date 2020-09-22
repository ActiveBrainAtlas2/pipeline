"""
@author: Xu Li, Mitra Lab, 2019
"""
import glob
import re
import sys

def natural_sort(l):
    convert = lambda text: int(text) if text.isdigit() else text.lower()
    alphanum_key = lambda key: [ convert(c) for c in re.split('([0-9]+)', key) ]
    return sorted(l, key = alphanum_key)

def main():

    ### -single or -list
    mode = sys.argv[1]
    if mode == '-single':
        PMDNO = sys.argv[2]
        imgNList = natural_sort(glob.glob('/nfs/data/main/*/jhuangU19/level_1/' + PMDNO + '_*/stitchedImage_ch2/*.tif'))
        with open('/nfs/data/main/M32/STP_RegistrationData/Lists/' + PMDNO + '_List.txt', 'w') as f:
            for item in imgNList:
                f.write('%s\n' % item)
    elif mode == '-list':
        listfile = sys.argv[2]
        for line in open(listfile, 'r'):
            PMDNO = line[0:7]
            print(PMDNO)
            #imgNList = natural_sort(glob.glob('/nfs/data/main/*/jhuangU19/level_1/' + PMDNO + '_*/stitchedImage_ch2/*.tif'))
            imgNList = natural_sort(glob.glob('/net/birdstore/Active_Atlas_Data/data_root/pipeline_data/DK39/preps/CH1/thumbnail/*.tif'))
            with open('/nfs/data/main/M32/STP_RegistrationData/Lists/' + PMDNO + '_List.txt', 'w') as f:
                for item in imgNList:
                    f.write('%s\n' % item)
if __name__ == "__main__":
    main()
