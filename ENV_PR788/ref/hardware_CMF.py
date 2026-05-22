# import cv2
import numpy as np
import serial
import time
import datetime
import os, sys
import logging
import re
import ctypes
import pandas as pd
from spectrum import raw_data_to_spectrum, spectrum_to_csv, csv_to_cmf,csv_to_spectrum
# from dftt_colour.transforms import tri_spectrum_to_srgb
# from draw import draw_color_square, plt_spectrum, plt_cmf
import matplotlib.pyplot as plt
# from transforms import ciexyz_to_srgb, np_srgb_encode, quantization


class PR788:

    def __init__(self, serial_port_name='COM3'):
        self._serial_com = serial.Serial(serial_port_name, baudrate=9600)

    def reconnect_serial(self):
        try:
            self._serial_com.close()
            self._serial_com.open()
        except Exception as exp:
            logging.error('CAN NOT OPEN SERIAL PORT' + str(exp))

    def close_serial(self):
        try:
            self._serial_com.close()
        except Exception as exp:
            logging.error('CAN NOT CLOSE SERIAL PORT' + str(exp))

    def remote_start(self):
        self.reconnect_serial()
        self._serial_com.write("P".encode('utf-8'))
        self._serial_com.write("H".encode('utf-8'))
        self._serial_com.write("O".encode('utf-8'))
        self._serial_com.write("T".encode('utf-8'))
        self._serial_com.write("O".encode('utf-8'))
        time.sleep(0.2)  # 0.2s between remote mode and duplex mode code
        self._serial_com.write('E'.encode('utf-8'))
        self._serial_com.write('1'.encode('utf-8'))
        self._serial_com.write('\r'.encode('utf-8'))
        self._serial_com.write('\n'.encode('utf-8'))

    def remote_terminate(self):
        self._serial_com.write('Q'.encode('utf-8'))
        # self.close_serial()

    def measure(self, code='5'):
        self._serial_com.write('M'.encode('utf-8'))
        self._serial_com.write(code.encode('utf-8'))
        self._serial_com.write('\r'.encode('utf-8'))
        self._serial_com.write('\n'.encode('utf-8'))
        serial_data_all = b''
        serial_data_count = 0
        while True:
            data_from_serial = self._serial_com.read()
            # print(s)
            serial_data_all += data_from_serial
            # print(current_time,current_time-start_time)
            serial_data_count += 1
            if re.search(r'^\s780,\d+(\.\d+e[+-]?\d+)?\r\n>', serial_data_all.decode('utf-8'), re.MULTILINE):
                # data style like ' 779,2.926e-06\r\n 780,2.855e-0\r\n>'
                logging.info('full read')
                break
        return serial_data_all


class MK350NP:
    # UPRTek MK550N Premium
    _mk_dll = ctypes.CDLL(r"D:\env788\dftt_colour\ExternalLibs\uSpectrum_Lib_v0.1.4.B06-20220602\LIB_VC\x64\mkusb.dll")
    _device_control_id = -1

    def __init__(self):
        try:
            # init_res = self._mk_dll.mk_Init(1, 300)
            init_res = self._mk_dll.mk_Init(0, 300)
            # self._deviceid = self._mk_dll.mk_FindFirst()
            # print(self._deviceid)
            scan_res = self._mk_dll.mk_SpDevScan()
            print(init_res)
            self._device_name_ptr = ctypes.c_char_p(b'')
            self._get_dev_res = self._mk_dll.mk_FindFirst(self._device_name_ptr)
            print(self._get_dev_res)
            if self._get_dev_res == 1:
                pass
            else:
                raise Exception('CAN NOT FIND A DEVICE')
            self._mk_dll.mk_OpenSpDev.argtypes = [ctypes.c_char_p]
            self._mk_dll.mk_OpenSpDev.restype = ctypes.c_int
            self._device_control_id = self._mk_dll.mk_OpenSpDev(self._device_name_ptr)
            if self._device_control_id == -1:
                raise Exception('GET DEVICE NAME STRING FAILED')
            else:
                pass
        except Exception as exp:
            logging.error('CAN NOT INITIALIZE MK550, ' + str(exp))

    def measure(self, is_auto=True, exp_time=60000):
        measure_status = self._mk_dll.mk_Msr_Capture(self._device_control_id, int(is_auto), exp_time)
        logging.info('Measure Returns' + str(measure_status))
        float_array = (ctypes.c_float * 402)()
        data_pointer = ctypes.cast(float_array, ctypes.POINTER(ctypes.c_float))
        get_data_status = self._mk_dll.mk_GetSpectrum(self._device_control_id, 380, 781, data_pointer)
        logging.info('Get Data Returns' + str(get_data_status))
        wl_list = []
        data_list = []
        for i in range(401):
            # print(data_pointer[i])
            wl_list.append(380 + i)
            data_list.append(data_pointer[i])
        return [wl_list, data_list]


def byte_data_to_csv(byte_data, csv_path, style='PR-788_M_5'):
    if style == 'PR-788_M_5':
        datas = re.findall(r'^\s(\d\d\d,\d+\.\d+e[+-]?\d+?)\r\n', byte_data.decode('utf-8'), re.MULTILINE)
        # data style like ' 779,2.926e-06\r\n 780,2.855e-0\r\n>'
    elif style == '':
        datas = ''
    else:
        raise Exception('Unknown/unsupported byte data style')
    csv_file = open(csv_path, 'w')
    for data in datas:
        csv_file.write(data + '\n')
    csv_file.close()
    # return datas


def byte_data_to_spectrum(byte_data, style='PR-788_M_5'):
    if style == 'PR-788_M_5':
        datas = re.findall(r'^\s(\d\d\d,\d+\.\d+e[+-]?\d+?)\r\n', byte_data.decode('utf-8'), re.MULTILINE)
    elif style == '':
        datas = ''
    else:
        raise Exception('Unknown/unsupported byte data style')
    data_df = pd.DataFrame(datas)
    data_df['wl'] = data_df[0].map(lambda x: x.split(',')[0])
    data_df['data'] = data_df[0].map(lambda x: x.split(',')[1])
    return raw_data_to_spectrum([data_df['wl'].astype(int).to_list(), data_df['data'].to_list()])


# def tri_spectrum_to_srgb(tri_spectrum):
#     xyz = tri_spectrum.integral
#     rgb = ciexyz_to_srgb(xyz)
#     srgb = np_srgb_encode(rgb)

#     return quantization(srgb, 8)


if __name__ == '__main__':

    model = "S1H_Sigma105mm"

    pr788 = PR788(serial_port_name='COM6')
    # # 寮€鏈?
    # pr788.remote_start()
    time.sleep(0.8)

    txt_count_path = 'mono_count.txt'
    with open(txt_count_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        spd_number = int(content)
    
    spd1 = byte_data_to_spectrum(pr788.measure())
    print(spd1)
    time1 = time.time()
    time1 = datetime.datetime.fromtimestamp(time1).strftime('%Y-%m-%d_%H.%M.%S.%f')
    print(time1)
    csv_dir = rf'D:\CMF_260502\{model}'
    csv_name = f'{spd_number}_{time1}.csv'
    spd_save_path = os.path.join(csv_dir,csv_name)
    spectrum_to_csv(spd1,spd_save_path)
    print(f"saved {spd_save_path}")

    new_spd_number = spd_number + 10
    with open(txt_count_path, 'w', encoding='utf-8') as f:
        f.write(str(new_spd_number))
    print(f'涓嬩竴涓祴閲忕殑娉㈡鏄細{new_spd_number}')

    # 鍏虫満
    # pr788.remote_terminate()
