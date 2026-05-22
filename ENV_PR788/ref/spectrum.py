import os.path
from math import ceil
from typing import Union

import numpy
import numpy as np
from scipy import interpolate
import pandas as pd
import matplotlib.pyplot as plt
from copy import deepcopy

import colour
# from numba import jit

# from transforms import cct_to_xy_cied

# 获取当前模块所在的目录路径
current_dir = os.path.dirname(__file__)

# todo 重构 性能太差了 各种检查是否有必要？是否直接填0即可？
class Spectrum:
    """
    Spectrum类对象
    属性：起点、终点、间隔、长度、有效长度、数据、描述、最大值
    方法：初始化、头尾填充0、去除头尾0、更改描述、重载乘、重载等于、字符串转换
    """
    _start = 300
    _end = 850
    _length = 550
    _data = []
    _description = ['']
    _max_val = 1  # 光谱尖峰的值
    _max_val_index = 300  # 光谱尖峰的位置

    # todo 保留原始数据间隔 以便之后调整插值算法
    # todo 从任意列数的csv里读取光谱信息
    # todo 可选csv有没有行名列名
    # todo spectrum需要一个全0值
    # todo 半峰宽FWHM，半峰下的start end范围

    @property
    def start(self):
        return self._start

    @property
    def end(self):
        return self._end

    @property
    def length(self):
        return self._length

    @property
    def valid_length(self):
        non_zero = np.nonzero(self._data)[0]
        if non_zero[-1] - non_zero[0] + 1 == len(non_zero):  # 确认非零部分中间没有断裂
            return len(np.nonzero(self._data)[0])
        else:
            return non_zero[-1] - non_zero[0] + 1

    @property
    def data(self):
        return self._data

    @property
    def description(self):
        return self._description

    @property
    def max_value(self):
        return self._max_val

    @property
    def max_position(self):
        return self._start + self._max_val_index

    @property
    def integral(self):
        return np.sum(self._data)

    def __init__(self, wl_start, wl_end, data, description=''):
        self._start = int(wl_start)
        self._end = int(wl_end)
        self._length = self._end - self._start + 1
        self._description = [description]
        x = np.linspace(self._start, self._end, self.length, dtype=int)
        if len(data) == len(x):
            self._data = np.array(data)
        else:
            raise Exception('data length does not match wave length range')
        self._max_val_index = np.argmax(self._data)
        self._max_val = self._data[self._max_val_index]

    def fill_zero(self, start: int, end: int):
        if start <= self._start:
            pass
        else:
            raise Exception('new range is smaller than original')
        if end >= self._end:
            pass
        else:
            raise Exception('new range is smaller than original')

        self._data = np.pad(self._data, (self._start - start, end - self._end), constant_values=(0, 0))
        self._start = start
        self._end = end
        self._length = self._end - self._start + 1
        return 0

    def trim_to_valid(self):
        non_zero = np.nonzero(self._data)[0]
        self._data = self._data[non_zero[0]:non_zero[-1] + 1]  # np slice
        self._end = self._start + non_zero[-1]
        self._start = self._start + non_zero[0]
        self._length = self._end - self._start + 1
        return 0

    def trim_to(self, wl_range: (tuple, list)):
        # todo 判断wl range的不同情况，填0或删除对应数据
        if wl_range[0]>=self._start and wl_range[1]<self._end:
            self._data = self._data[wl_range[0]-self._start: wl_range[1] -self._start+1]
            self._end = wl_range[1]
            self._start = wl_range[0]
            self._length = wl_range[1] - wl_range[0] + 1
            self._max_val_index = np.argmax(self._data)
            self._max_val = self._data[self._max_val_index]
        else:
            raise Exception('given trim range exceeds current range')
        return 0

    def get_data(self, wl: int):
        if wl in range(self._start, self._end + 1):
            return self._data[wl - self._start]
        else:
            return None

    def normalize(self):
        self._data = self._data / self._max_val
        self._max_val = self._data[self._max_val_index]
        # print(self._data)

    def desciption_change(self, content: str, behavior: str = 'append'):
        if isinstance(content, str):
            pass
        else:
            raise Exception('content must be str')

        if behavior == 'append':
            self._description.append(content)
        elif behavior == 'rewrite':
            self._description = [content]
        else:
            pass

        return 0

    def __mul__(self, other):
        temp_obj = deepcopy(self)
        temp_wl_start = self._start
        temp_wl_end = self._end
        if isinstance(other, Spectrum):
            if self._start == other._start and self._end == other._end:  # 两个对象的光谱起点终点一样，可以直接互相乘
                temp_data = self._data * other._data
            else:
                temp_data_self = np.copy(self._data)
                temp_data_other = np.copy(other._data)
                if self._start > other._start:
                    head = self._start - other._start
                    temp_data_other = np.delete(temp_data_other, np.s_[0:head])
                else:
                    head = other._start - self._start
                    temp_data_self = np.delete(temp_data_self, np.s_[0:head])
                    temp_wl_start = other._start
                if self._end < other._end:
                    tail = other._end - self._end
                    temp_data_other = np.delete(temp_data_other, np.s_[len(temp_data_other) - tail - 1:-1])
                else:
                    tail = self._end - other._end
                    temp_data_self = np.delete(temp_data_self, np.s_[len(temp_data_self) - tail - 1:-1])
                    temp_wl_end = other._end
                temp_data = np.multiply(temp_data_self, temp_data_other)
        elif isinstance(other, (int, float)):
            temp_data = self._data * other
        else:
            raise Exception('undefined multiply')
        temp_obj._start = temp_wl_start
        temp_obj._end = temp_wl_end
        temp_obj._data = temp_data
        temp_obj._length = temp_wl_end - temp_wl_start + 1
        temp_obj._max_val_index = np.argmax(temp_data)
        temp_obj._max_val = temp_obj._data[temp_obj._max_val_index]

        return temp_obj

    # todo 光谱和CMF能实现乘法交换率

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, other):
        temp_obj = deepcopy(self)
        temp_wl_start = self._start
        temp_wl_end = self._end
        if isinstance(other, Spectrum):
            if self._start == other._start and self._end == other._end:  # 两个对象的光谱起点终点一样，可以直接互相乘
                temp_data = self._data / other._data
            else:
                temp_data_self = np.copy(self._data)
                temp_data_other = np.copy(other._data)
                if self._start > other._start:
                    head = self._start - other._start
                    temp_data_other = np.delete(temp_data_other, np.s_[0:head])
                else:
                    head = other._start - self._start
                    temp_data_self = np.delete(temp_data_self, np.s_[0:head])
                    temp_wl_start = other._start
                if self._end < other._end:
                    tail = other._end - self._end
                    temp_data_other = np.delete(temp_data_other, np.s_[len(temp_data_other) - tail - 1:-1])
                else:
                    tail = self._end - other._end
                    temp_data_self = np.delete(temp_data_self, np.s_[len(temp_data_self) - tail - 1:-1])
                    temp_wl_end = other._end
                temp_data = np.true_divide(temp_data_self, temp_data_other)
        elif isinstance(other, (int, float)):
            temp_data = self._data / other
        else:
            raise Exception('undefined multiply')
        temp_obj._start = temp_wl_start
        temp_obj._end = temp_wl_end
        temp_obj._data = temp_data
        temp_obj._length = temp_wl_end - temp_wl_start + 1
        temp_obj._max_val_index = np.argmax(temp_data)
        temp_obj._max_val = temp_obj._data[temp_obj._max_val_index]

        return temp_obj

    def __add__(self, other):
        temp_obj = deepcopy(self)
        temp_wl_start = self._start
        temp_wl_end = self._end
        if isinstance(other, Spectrum):
            if self._start == other._start and self._end == other._end:
                temp_data = self._data + other._data
            else:
                temp_data_self = np.copy(self._data)
                temp_data_other = np.copy(other._data)
                if self._start > other._start:
                    self.fill_zero(other._start, self._end)
                else:
                    other.fill_zero(self._start, other._end)
                if self._end < other._end:
                    self.fill_zero(self._start, other._end)
                else:
                    other.fill_zero(other._start, self._end)
                temp_data = self._data + other._data
        else:
            raise Exception('undefined add')
        temp_obj._start = self._start
        temp_obj._end = self._end
        temp_obj._data = temp_data
        temp_obj._length = self._end - self._start + 1

        return temp_obj

    def __eq__(self, other):
        if isinstance(other, Spectrum):
            return self._start == other._start and self._end == other._end and np.array_equal(self._data,
                                                                                              other._data)
        else:
            raise Exception('Comparison is only valid between two Spectrum objects')

    def __repr__(self):
        return 'Spectrum | start:{}nm, end:{}nm, length:{}nm, max:{:.2e} @ {}nm, description:{}'.format(
            self._start,
            self._end,
            self._length,
            self.max_value,
            self.max_position,
            self._description
        )


class CMF:
    """
    三个Spectrum对象构成一个CMF
    属性：CMF的X、Y、Z，描述
    方法：初始化、求积分、更改描述、重载乘、字符串转换
    """
    _x: Spectrum
    _y: Spectrum
    _z: Spectrum
    _description = ['']

    @property
    def x(self):
        return self._x

    @property
    def y(self):
        return self._y

    @property
    def z(self):
        return self._z

    @property
    def description(self):
        return self._description

    @property
    def integral(self):
        return np.array([self._x.integral, self._y.integral, self._z.integral])

    def __init__(self, x: Spectrum, y: Spectrum, z: Spectrum, description=''):
        self._x = x
        self._y = y
        self._z = z
        self._description = [description]

    def desciption_change(self, content: str, behavior: str = 'append'):
        if isinstance(content, str):
            pass
        else:
            raise Exception('content must be str')

        if behavior == 'append':
            self._description.append(content)
        elif behavior == 'rewrite':
            self._description = [content]
        else:
            pass

    def trim_to(self,wl_range:(tuple,list)):
        self._x.trim_to(wl_range)
        self._y.trim_to(wl_range)
        self._z.trim_to(wl_range)

    def __mul__(self, other):
        temp_obj = deepcopy(self)
        if isinstance(other, (Spectrum, int, float)):
            temp_obj._x = temp_obj._x * other
            temp_obj._y = temp_obj._y * other
            temp_obj._z = temp_obj._z * other
        else:
            raise Exception('undefined multiply')
        return temp_obj

    def __rmul__(self, other):
        return self.__mul__(other)

    def __repr__(self):
        return 'CMF | description:{}\n{}\n{}\n{}'.format(
            self._description,
            str(self._x),
            str(self._y),
            str(self._z)
        )


def raw_data_to_spectrum(raw_data, inter_kind='linear', description=''):
    """
    raw_data是一个如下所示的list:
    [[波长],[数据]]
    """
    wl = raw_data[0]
    data = raw_data[1]

    start = int(ceil(wl[0]))  # 用进一法得到数据起点
    end = int(wl[-1])  # 去尾法得到终点

    x = np.linspace(start, end, end - start + 1, dtype=int)  # 构建线性空间，强制数据类型为int
    interfunc = interpolate.interp1d(wl, data, kind=inter_kind)  # 从散点数据构建空间
    new_data = interfunc(x)  # 数据插值到np的线性空间

    return Spectrum(start, end, new_data, description)  # 返回数据间隔为1nm的Spectrum对象


def csv_to_spectrum(csv_path, inter_kind='linear', description='', csv_header: int = None, column_num=1):
    if csv_header is None:
        df = pd.read_csv(csv_path, header=None)
        df.columns = ['wl', 'value']  # wl指wave length
    else:
        df = pd.read_csv(csv_path, header=csv_header)
    # df['wl'].astype('int32')
    # todo 判断并自动支持非整数波长数据
    wl = df['wl'].to_list()
    spec_data = df['value'].to_list()
    # if column_num == 1:
    #     wl = df['wl'].to_list()
    #     spec_data = df['value'].to_list()
    # else:
    # todo 把这个方法写完 满足读取多列csv的要求

    return raw_data_to_spectrum([wl, spec_data], inter_kind, description)  # 返回数据间隔为1nm的Spectrum对象


def spectrum_to_csv(spectrum, dest_path):
    wavelengths = np.linspace(
        spectrum.start,
        spectrum.end,
        spectrum.end - spectrum.start + 1,
        dtype=int
    ).tolist()
    values = spectrum.data.tolist()
    temp_list = [wavelengths, values]
    '''
    以上构建一个长这样的list:
    [[波长],[数据]]
    '''
    # print(temp_list)
    df = pd.DataFrame(temp_list)
    df = df.T  # 转置一下把它竖起来
    df.to_csv(dest_path, header=False, index=False)  # 不要行列名
    data_dict = dict(zip(wavelengths, values))
    return colour.SpectralDistribution(data_dict, name='Measured')
    # return 0


def csv_to_cmf(csv_path, inter_kind='linear', description=''):
    df = pd.read_csv(csv_path, header=None)
    df.columns = ['wl', 'r', 'g', 'b']
    wl = df['wl'].to_list()
    r_data = df['r'].to_list()
    g_data = df['g'].to_list()
    b_data = df['b'].to_list()

    r_cmf = raw_data_to_spectrum([wl, r_data], inter_kind)
    g_cmf = raw_data_to_spectrum([wl, g_data], inter_kind)
    b_cmf = raw_data_to_spectrum([wl, b_data], inter_kind)

    return CMF(r_cmf, g_cmf, b_cmf, description)


def color_temp_to_spectrum_cied(cct):
    if isinstance(cct, (int, float)):
        cie_d_csv_path = os.path.join(current_dir, 'Builtin_data', 'CIE_D_S0S1S2.csv')
        cie_d_s0s1s2 = csv_to_cmf(cie_d_csv_path)
        cct_cied_xy = cct_to_xy_cied(cct)
        d_illuminant_m = 0.0241 + 0.2562 * cct_cied_xy[0] - 0.7341 * cct_cied_xy[1]
        m1 = (-1.3515 - 1.7703 * cct_cied_xy[0] + 5.9114 * cct_cied_xy[1]) / d_illuminant_m
        m2 = (0.03 - 31.4424 * cct_cied_xy[0] + 30.0717 * cct_cied_xy[1]) / d_illuminant_m

        return cie_d_s0s1s2.x + m1 * cie_d_s0s1s2.y + m2 * cie_d_s0s1s2.z
    else:
        raise Exception('cct must be a number(int or float)')


def color_temp_to_spectrum_blackbody(cct, wl_range):
    """
    :param cct: cct in int or float
    :param wl_range: wavelength range of intended output spectrum object, must be a tuple or a list consist of EXACTLY
    two numbers.
    :return: a spectrum object which represents the blackbody radiation of the input cct
    """
    h = 6.626176e-34  # Plank constant
    c = 2.99792458e+8  # velocity of light
    k = 1.380662e-23  # Boltzmann constant
    c1 = 2 * np.pi * h * c ** 2
    c2 = h * c / k
    data_list = []
    for _lambda in range(wl_range[0], wl_range[1] + 1):
        _lambda = _lambda * 1e-9
        m_e = c1 / (_lambda ** 5 * (
                np.e ** (c2 / (cct * _lambda)) - 1
        ))
        data_list.append(m_e)
    wl = np.linspace(wl_range[0], wl_range[1], wl_range[1] - wl_range[0] + 1)

    spectrum_blackbody = raw_data_to_spectrum([wl, data_list])
    spectrum_blackbody.normalize()

    return spectrum_blackbody


cmf_cie1931xyz = csv_to_cmf(os.path.join(current_dir, 'Builtin_data', '1931-2d-1nm-360-830.csv'))

if __name__ == '__main__':
    print(color_temp_to_spectrum_blackbody(3200, [380, 780]))
    print(color_temp_to_spectrum_cied(6500))
