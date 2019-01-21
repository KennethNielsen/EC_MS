# -*- coding: utf-8 -*-
"""
Created on Tue Jul 19 10:40:46 2016
@author: Scott

This is the core file of the package. Includes functions for combining datasets.
"""

# make python2-compatible:
from __future__ import print_function
from __future__ import division

import time
import re
import os #, sys    
import numpy as np




def synchronize(data_objects, t_zero='start', append=None, file_number_type='EC',
                cutit=False, cut_buffer=60, override=None, update=True, tz=None,
                verbose=True, vverbose=False):
    '''
    'synchronize' is the most important function of electropy/ECpy/EC_MS/EC_Xray
    
    It combines numpy array data from multiple dictionaries into a single 
    dictionary with all time variables aligned according to absolute time.
    If cutit=True, data will be retained in the interval of overlap. Otherwise,
    all data will be retained, but with t=0 at the start of the overlap,
    unless t_zero is specified (details below). 
    If append=True, data columns of the same name will be joined and filled with
    zeros for sets that don't have them so that all columns remain the same length
    as their time columns, and a data column 'file number' will be added to 
    keep track of where the data comes from. 
    
    ----  inputs -----
        data_objects: traditionally a list of dictionaries, each of which has
    a key ['data_cols'] pointing to a list of keys for columns of data to be
    synchronized. data_objects can also contain objects with attribute data, in
    which data_objects[i].data is used in the same way as data_objects normally is,
    and then, if update is True, replaced by the combined data set.
        t_zero: a string or number representing the moment that is considered t=0
    in the synchronized dataset. If t_zero is a number, it is interpreted as a
    unix epoch time. t_zero='start' means it starts at the start of the overlap. 
    'first' means t=0 at the earliest datapoint in any data set.
        append: True if identically named data columns should be appended. False
    if the data from the individual sets should be kept in separate columns. By 
    default (append=None), append will be set inside the function to True if all of
    the data sets have the same 'data type'.
        file_number_type: When appending data, a column file_number is added
    storing the file numbers corresponding to the data from datasets of type
    file_number_type. combined_data['file number'] will thus have the same length
    as combined_data[timecol] where timecol is the time variable for that data
    type, i.e. 'time/s' for file_number_type='EC', as is the default.
        cutit: True if data from outside the timespan where all input datasets
    overlap should be removed. This can make things a bit cleaner to work with 
    in the front-panel scripts.
        override: True if you don't want the function to pause and ask for your
    consent to continue in the case that there is no range of overlap in the datasets.
    override = False helps you catch errors if you're importing the wrong datasets.
    By default, override gets set to True if append is True. 
        update: True if you want object.data to be replaced with the synchronized
    dataset for any non-dictionary objects in data_objects
        tz: timezone for genrating timestamp, as pytz.timezone() instance or string 
    to be read by pytz.timezone(). Local timezone assumed by default.
        verbose: True if you want the function to talk to you. Recommended, as it
    helps catch your mistakes and my bugs. False if you want a clean terminal or stdout
    
    ---- output ----
        the combined and synchronized data set, as a dictionary
    
    It's really quite nice... 
    But it's a monster function.
    There's lots of comments in the code to explain the reasoning.
    I'm happy for suggestions on how to improve! scott@fysik.dtu.dk
    
    '''
    if verbose:
        print('\n\nfunction \'synchronize\' at your service!') 
        
    from .Data_Importing import timestamp_to_epoch_time, epoch_time_to_timestamp
    
    if type(data_objects) is not list:
        print('''The first argument to synchronize should be a list of datasets! 
                You have instead input a dictionary as the first argument. 
                I will assume that the first two arguments are the datasets you
                would like to synchronize with standard settings.''')
        data_objects = [data_objects, t_zero]
        t_zero = 'start'
    
    # figure out which of the inputs, if any, are objects with attribute 'data' vs simply datasets:
    datasets = []
    objects_with_data = []
    for i, dataset in enumerate(data_objects):
        if type(dataset) is dict:
            datasets += [dataset]
        else:
            try:
                data = dataset.data
            except AttributeError:  # just ignore objects that don't have attribute 'data'.
                print('can\'t get data from data_object number ' + str(i))
                continue
            objects_with_data += [dataset]
            datasets += [data]       
    
    if append is None: #by default, append if all datasets are same type
        append = len({d['data_type'] for d in datasets}) == 1
    if override is None:
        override = append  # Without override, it checks for overlap.
                           # So, I should override when I expect no overlap.
                           # I expect no overlap when appending datasets
                           # Thus, override should be True when append is True.
    if verbose:
        print('append is ' + str(append))
    
    now = time.time()  #now in unix epoch time, 
    # ^ which is necessarily larger than the acquisition epochtime of any of the data.
               #prepare to collect some data in the first loop:
    recstarts = []            #first recorded time in unix epoch time
    t_start = 0               #latest start time (start of overlap) in unix epoch time
    t_finish = now            #earliest finish time (finish of overlap) in unix epoch time
    t_first = now             #earliest timestamp in unix epoch time
    t_last = 0                #latest timestamp in unix epoch time
    hasdata = {}              #'combining number' of dataset with False if its empty or True if it has data
    
    combined_data = {'data_type':'combined', 'data_cols':[]}
    title_combined = ''
    
    #go through once to generate the title and get the start and end times of the files and of the overlap
    if verbose:
        print('---------- syncrhonize entering first loop -----------')

    for nd, dataset in enumerate(datasets):
        dataset['combining_number'] = nd
        if 'data_cols' not in dataset or len(dataset['data_cols']) == 0:
            print(dataset['title'] + ' is empty')
            hasdata[nd] = False
            recstarts += [now] # don't want dataset list to be shortened 
            #when sorted later according to recstarts!
            continue     #any dataset making it to the next line is not empty, i.e. has data.
        hasdata[nd] = True    
        if len(title_combined) > 0:
            title_combined += ', '
            if nd == len(datasets) - 1:
                title_combined += 'and '
        title_combined += '(' + dataset['title'] + ') as ' + str(nd)
        if verbose:
            print('working on ' + dataset['title'])
        
        try:
            t_0 = dataset['tstamp'] # UNIX epoch time !!! The t=0 for the present dataset
        except KeyError:
            print('No tstamp in dataset. Trying to read it from date and timestamp.')
            date = None
            timestamp = None
            if 'date' in dataset:
                date = dataset['date']
            if 'timestamp' in dataset:
                timestamp = dataset['timestamp']
            t_0 = timestamp_to_epoch_time(timestamp, date, tz=tz, verbose=verbose)

        if verbose:
                print('\ttstamp is ' + str(t_0) + ' seconds since Epoch')

        t_s = now           # will decrease to the earliest start of time data in the dataset        
        t_f = 0             # will increase to the latest finish of time data in the dataset
        
        for col in dataset['data_cols']:
            #print('col = ' + str(col)) # debugging
            if is_time(col):
                try:
                    t_s = min(t_s, t_0 + dataset[col][0])   
                    # ^ earliest start of time data in dataset in epoch time
                    t_f = max(t_f, t_0 + dataset[col][-1])  
                    # ^ latest finish of time data in dataset in epoch time
                except IndexError:  #if dataset['data_cols'] points to nonexisting data, something went wrong.
                    print(dataset['title'] + ' may be an empty file.')
                    hasdata[nd] = False # files that are empty after the header are caught here
                    
        if not hasdata[nd]:  # move on from empty files
            continue
        recstarts += [t_s]               #first recorded time
    
        t_first = min([t_first, t_0])    #earliest timestamp  
        t_last = max([t_last, t_0])      #latest timestamp 
        t_start = max([t_start, t_s])    #latest start of time variable overall
        t_finish = min([t_finish, t_f])  #earliest finish of time variable overall
    
    # out of the first loop. We've got the title to be given to the new combined dataset, 
    # the tspan of all the data in unix epoch time, info on which sets if any are empty,
    # and the start of data recording for each data set. Now, we save that info
    # and use it to get ready for the second loop.
    
    # t_zero is the UNIX epoch time corresponding to t=0 in the retunred data set.
    # It can be 'first', 'last', 'start', or 'finish', which work as illustrated here:
    # | = timestamp, *--* = data acquisition
    # dataset1 | *----------------------------*
    # dataset2 |       *-----------------------------------------*
    # dataset3              |     *----------------------*
    # t =      first        last  start      finish            
    if verbose:
        print('first: ' + str(t_first) + ', last: ' + str(t_last) + 
        ', start: ' + str(t_start) + ', finish: ' + str(t_finish))   
        
    if t_start > t_finish and not override:
        print('No overlap. Check your files.\n')
        offerquit()  
        
    if t_zero == 'start':
        t_zero = t_start
    elif t_zero == 'first':
        t_zero = t_first
    elif t_zero == 'last':
        t_zero = t_last
    elif t_zero == 'finish':
        t_zero = t_finish
    
    # some stuff is now ready to put into combined_data:
    
    combined_data['title'] = title_combined
    combined_data['tspan_0'] = [t_start, t_finish] 
    # ^ overlap start and finish times as unix epoch times
    combined_data['tspan_1'] = [t_start - t_first, t_finish - t_first]    
    # ^ overlap start and finish times as seconds since earliest start 
    combined_data['tspan'] = [t_start - t_zero, t_finish - t_zero]    
    # ^ start and finish times of overlap as seconds since t=0  
    combined_data['tspan_2'] = combined_data['tspan'] #old code calls this tspan_2.

    combined_data['tstamp'] = t_zero
    combined_data['timestamp'] = epoch_time_to_timestamp(t_zero, tz=tz, verbose=verbose) 
    # ^ we want that timestamp refers to t=0
    
    combined_data['first'] = t_first - t_zero
    combined_data['last'] = t_last - t_zero
    combined_data['start'] = t_start - t_zero
    combined_data['finish'] = t_finish - t_zero

    # Deal with the cases that all or all but one dataset is empty:
    N_notempty = len([1 for v in hasdata.values() if v==1])
    if N_notempty == 0:
        print('First loop indicates that no files have data!!! ' + 
              'synchronize will return an empty dataset!!!')
    elif N_notempty == 1:
        print('First loop indicates that only one dataset has data! ' + 
              'Synchronize will just return that dataset!')
        combined_data = next(datasets[nd] for nd, v in hasdata.items() if v==1)
        print('\nfunction \'synchronize\' finished!\n\n')
        return combined_data
    
    # Sort datasets by start of recording so that in the second loop they are combined in the right order   
    I_sort = np.argsort(recstarts)    
    datasets = [datasets[I] for I in I_sort]       
        #note: EC lab techniques started together have same tstamp but different recstart
    
    # It's very nice when appending data from multiple files (EC data especially, 
    # from experience), to be able to select data later based on file number
    if (append and 
        file_number_type in {d['data_type'] for d in datasets}): 
        combined_data['file number'] = [] 
        fn_timecol = get_timecol(data_type=file_number_type)
        
    combined_data_keys_0 = list(combined_data.keys()) 
# used to avoid overwriting metadata at end of second loop
    
    # ... And loop again to synchronize the data and put it into the combined dictionary.
    if verbose:
        print('---------- syncrhonize entering second loop -----------')
        
    for i, dataset in enumerate(datasets):
        nd = dataset['combining_number']
        # ^ note, nd is the number of the dataset from the first loop, and is 
        #not scrambled by the sorting of the datasets according to recstart done above.
        if verbose:
            print('working on dataset ' + dataset['title'] + 
                  ', which has combining number = ' + str(nd))
            #print('cols in ' + dataset['title'] + ':\n' + str(dataset['data_cols']))
            #print('cols in combined_data:\n' + str(combined_data['data_cols']))
        if not hasdata[nd]: 
            if verbose:
                print('skipping this dataset, because its combining number, ' + 
                      str(nd) + ', is in the empty files list')
            continue
            
        # the synchronization is based on the offset of the individual dataset
        # with respect to t_zero, both in unix time.
        t_0 = dataset['tstamp']
        offset = t_0 - t_zero
        
        # Prepare to cut based on the absolute (unix epoch) time interval. 
        if cutit:
            masks = {}     #will store a mask for each timecol to cut the corresponding cols with
            for col in dataset['data_cols']:     
                if is_time(col):
                    if verbose:
                        print('preparing mask to cut according to timecol ' + col)
                    t = dataset[col]
                    masks[col] = np.logical_and((t_start - t_0 - cut_buffer) < t, 
                                                 t < (t_finish - t_0 + cut_buffer))
                    
        # Check how many rows will be needed for relevant data types when appending data,
        #and append to in the 'file number' column
        if append:
            # sometimes, a certain data col is absent from some files of the same
            #data type, but we still want it to match up with the corresponding 
            #time variable for the rest of the files in combined_data. The most
            #common example is OCV between other methods in EC data, which has no 
            #current. When that happens, we want the filler values 0 to make sure
            #all the collumns line up. oldcollength and collength will help with that:
            oldcollength = {} # will store the existing length of each data col
            for col in combined_data['data_cols']:
                if is_time(col):
                    oldcollength[col] = len(combined_data[col])
            collength = {}  # will store the length to be appended to each data col
            for col in dataset['data_cols']:
                if is_time(col):
                    collength[col] = len(dataset[col])
                    if col not in oldcollength.keys():
                        oldcollength[col] = 0
                    else: #the case that the timecol is in both combined_data and dataset
                        if vverbose:  
                            print('prepared to append data according to timecol ' + col)
            # now, fill in file number according to datasets of type file_number_type            
            if dataset['data_type'] == file_number_type: 
                fn = np.array([i] * collength[fn_timecol])             
                combined_data['file number'] = np.append(combined_data['file number'], fn) 
                if verbose:    
                    print('len(combined_data[\'file number\']) = ' + str(len(combined_data['file number'])))
                    
        # now we're ready to go through the columns and actually process the data
        #for smooth entry into combined_data
        for col in dataset['data_cols']:
            data = dataset[col]
            # processing: cutting
            if cutit:           #cut data to only return where it overlaps
                #print('cutting ' + col) # for debugging
                try:
                    data = data[masks[get_timecol(col)]]  
                except KeyError:
                    print('')
            # processing: offsetting 
            if is_time(col):
                data = data + offset
            # processing: for appended data
            if append:
                # get data from old column for appending
                if col in combined_data:
                    olddata = combined_data[col]    
                else:
                    olddata = np.array([])
                #but first...
                # proccessing: ensure elignment with timecol for appended data
                l1 = len(data) + len(olddata)
                #print('col = ' + col) #debugging
                timecol = get_timecol(col)
                #print('timecol = ' + str(timecol)) #debugging
                try:
                    l0 = oldcollength[timecol] + collength[timecol] 
                except KeyError:
                    print(col + ' should have timecol ' + timecol + ' but this is ' + 
                          ' not in dataset. Removing ' + col + ' from data_cols.')
                    dataset['data_cols'].remove(col)
                    continue
                # ^ I had to get these lengths before because I'm not sure whether 
                #timecol will have been processed first or not...
                if l0 > l1: #this is the case if the previous dataset was missing col but not timecol
                    filler = np.array([0] * (l0 - l1))
                    olddata = np.append(olddata, filler) 
                    # ^ and now len(olddata) = len(combined_data[timecol])
                # APPEND!
                data = np.append(olddata, data)
            # processing: ensuring unique column names for non-appended data
            else:
                if col in combined_data:
                    print('conflicting versions of ' + col + '. adding subscripts.')
                    col = col + '_' + str(nd)                        
            
            # ---- put the processed data into combined_data! ----
            combined_data[col] = data
            # And make sure it's in data_cols
            if col not in combined_data['data_cols']:
                combined_data['data_cols'].append(col)  
         
        
        #keep the metadata from the original datasets
        for col, value in dataset.items():
            if col in combined_data['data_cols']:
                continue # Otherwise I duplicate all the data.
            if col[0] == '_': #let's keep it to one level of '_', and nest dictionaries
                #print(col)
                if col in combined_data: 
                    if nd in combined_data[col] and vverbose:
                        print('overwriting ' + col + '[' + str(nd) + '] with nested metadata.')
                    combined_data[col][nd] = value
                else:
                    combined_data[col] = {nd:value}
                    if verbose:
                        print('nesting metadata for ' + col + ', nd = ' + str(nd))
                continue
            if col not in combined_data_keys_0: # avoid ovewriting essentials
                combined_data[col] = value # this will store that from the
                                           #latest dataset as top-level
            col = '_' + col  # new name so that I don't overwrite
                #essential combined metadata like tstamp
            if col in combined_data:
                #print(col) #debugging
                if nd in combined_data[col]:
                    if verbose:
                        print(col + '[' + str(nd) + '] has nested metadata, skipping unnested.')
                else:        
                    combined_data[col][nd] = value
            else:
                # I expect to arrive here only once, so good place for output
                if vverbose:
                    print('metadata from original files stored as ' + col)
                combined_data[col] = {nd: value}

    # ----- And now we're out of the loop! --------               
    
    # There's still a column length problem if the last dataset is missing 
    #columns! Fixing that here. 
    for col in combined_data['data_cols']:
        l1 = len(combined_data[col])
        timecol = get_timecol(col)
        #print('about to cut ' + col + ' according to timecol ' + timecol) # debugging
        try:
            l0 = len(combined_data[timecol])
        except KeyError:
            print('can\'t find timecol for {}. skipping.'.format(col))
        if l0 > l1:
            filler = np.array([0] * (l0 - l1))
            combined_data[col] = np.append(combined_data[col], filler)
    
    # add 'file number' to data_cols
    if 'file number' in combined_data.keys() and 'file number' not in combined_data['data_cols']:    
        combined_data['data_cols'].append('file number') #for new code
    
    # add 't_str' to the data set (don't know where else to do it)
    if 'time/s' in combined_data.keys():
        combined_data['t_str'] = 'time/s'

    # check that there's actually data in the result of all this        
    if len(combined_data['data_cols']) == 0:
        print('The input did not have recognizeable data! Synchronize is returning an empty dataset!')    

    # update the objects (e.g. ScanImages object in EC_Xray). This is nice!
    if update:
        for instance in objects_with_data:
            instance.data = combined_data
    
    # and, we're done!
    if verbose:
        print('function \'synchronize\' finsihed!\n\n')   
    
    return combined_data        


    
def cut(x, y, tspan=None, returnindeces=False, override=False):
    '''
    Vectorized 17L09 for EC_Xray. Should be copied back into EC_MS
    '''
    if tspan is None:
        return x, y
    
    if np.size(x) == 0:
        print('\nfunction \'cut\' received an empty input\n')
        offerquit()
        
    mask = np.logical_and(tspan[0]<x, x<tspan[-1])
    
    if True not in mask and not override:
        print ('\nWarning! cutting like this leaves an empty dataset!\n' +
               'x goes from ' + str(x[0]) + ' to ' + str(x[-1]) + 
                ' and tspan = ' + str(tspan) + '\n')
        offerquit()
        
    x = x.copy()[mask]
    y = y.copy()[mask]
    
    if returnindeces:
        return x, y, mask #new 17H09
    return x, y


def timeshift(dataset, t_zero='start'):
    if t_zero is None:
        t0 = 0
    elif t_zero == 'start':
        t0 = dataset['tspan'][0]
    else:
        t0 = t_zero
    for col in dataset['data_cols']:
        if is_time(col):
            #print(f'{col},\n{dataset[col]},\nt0 = {t0}') # debugging
            dataset[col] -= t0
    tspan = dataset['tspan']
    dataset['tspan'] = [tspan[0]-t0, tspan[-1]-t0]
    return dataset


def cut_dataset(dataset_0, tspan=None, t_zero=None, verbose=True):
    '''
    Makes a time-cut of a dataset. Written 17H09.
    Unlike time_cut, does not ensure all MS data columns are the same length.
    '''
    if verbose:
        print('\n\nfunction \'cut dataset\' at your service!\n') 
    dataset = dataset_0.copy()
    dataset['data_cols'] = dataset['data_cols'].copy()
    if tspan is None:
        return dataset
    #print(dataset['title'])
    time_masks = {} #I imagine storing indeces improves performance
    for col in dataset['data_cols']:
        timecol = get_timecol(col)
        #print(col + ', length = ' + str(len(dataset[col]))) # debugging  
        if timecol in time_masks.keys():
            #print('already got indeces, len = ' + str(len(indeces[timecol]))) #debugging
            mask = time_masks[timecol]
        else:
            #print(timecol + ', length = ' + str(len(dataset[timecol]))) #debugging  
            t = dataset[timecol]
            mask = np.logical_and(tspan[0]<t, t<tspan[-1])
            time_masks[timecol] = mask
#        print('about to cut!') # debugging
        dataset[col] = dataset[col].copy()[mask]
    dataset['tspan'] = tspan
    timeshift(dataset, t_zero)
    if verbose:
        print('\nfunction \'cut dataset\' finsihed!\n\n') 
    return dataset


def offerquit():
    yn = input('continue? y/n\n')
    if yn == 'n':
        raise SystemExit

    
def is_time(col, verbose=False):
    '''
    determines if a column header is a time variable, 1 for yes 0 for no
    '''
    if verbose:
        print('\nfunction \'is_time\' checking \'' + col + '\'!')
    col_type = get_type(col)
    if col_type == 'EC':
        if col[0:4]=='time':
            return True
        return False
    elif col_type in ['MS', 'cinfdata']:
        if col[-2:] == '-x': 
            return True
        return False
    elif col_type == 'Xray':
        if col == 't':
            return True
        return False
    #in case it the time marker is just burried in a number suffix:
    ending_object = re.search(r'_[0-9][0-9]*\Z',col) 
    if ending_object:
        col = col[:ending_object.start()]
        return is_time(col)
    print('can\'t tell if ' + col + ' is time. Returning False.')
    return False

def is_MS_data(col):
    if re.search(r'^M[0-9]+-[xy]', col):
        return True
    return False

def is_EC_data(col):
    from .EC import EC_cols_0
    if col in EC_cols_0:
    #this list should be extended as needed
        return True
    if col is None:
        return False
    if col[-1] == '*' and col[:-1] in EC_cols_0:
        return True
    return False

def is_Xray_data(col):
    if is_EC_data(col):
        return False
    if is_MS_data(col):
        return False
    return True

def get_type(col):
    if is_EC_data(col):
        return 'EC'
    if is_MS_data(col):
        return 'MS'
    elif col[-2:] in ['-x', '-y']:
        return 'cinfdata' #it's cinfdata but not from a mass channel
    if col is None:
        return None
    return 'Xray' # to be refined later...

def get_timecol(col=None, data_type=None, verbose=False):
    if data_type is None:
        data_type = get_type(col)
    if data_type == 'EC':
        timecol = 'time/s'
    elif data_type == 'MS':
        if col is None:
            timecol = 'M4-x' # probably the least likely timecol to be missing from MS data
        else:
            timecol = col[:-2] + '-x'
    elif data_type == 'Xray':
        timecol = 't' # to be refined later...
    elif col[-2:] in ['-y', '-x']: # a timecol is its own timecol
        timecol = col[:-2] + '-x' #for any data downloaded from cinfdata
    else:
        print('couldn\'t get a timecol for ' + col + 
              '. data_type=' + str(data_type))
        timecol = None
    if verbose:
        print('\'' + str(col) + '\' should correspond to timecol \'' + str(timecol) +'\'')
    return timecol

def timestamp_to_seconds(timestamp):
    '''
    seconds since midnight derived from timestamp hh:mm:ss
    '''
    h = int(timestamp[0:2])
    m = int(timestamp[3:5])
    s = int(timestamp[6:8])
    seconds = 60**2 *h + 60 *m + s
    return seconds
    
def seconds_to_timestamp(seconds):
    '''
    timestamp hh:mm:ss derived from seconds since midnight
    '''
    h = int(seconds/60**2)
    seconds = seconds - 60**2 *h
    m = int(seconds/60)
    seconds = seconds - 60 *m
    s = int(seconds)
    timestamp = '{0:2d}:{1:2d}:{2:2d}'.format(h,m,s)
    timestamp = timestamp.replace(' ','0')
    return timestamp

def dayshift(dataset, days=1):
    ''' Can work for up to 4 days. After that, hh becomes hhh... 
    This function should find little use now that 
    '''
    dataset['timestamp'] = seconds_to_timestamp(timestamp_to_seconds(dataset['timestamp']) + days*24*60*60) 
    return dataset



def sort_time(dataset, data_type='EC', verbose=False, vverbose=False):
    #17K11: This now operates on the original dictionary, so
    #that I don't need to read the return.
    if verbose:
        print('\nfunction \'sort_time\' at your service!\n\n')
    
    if 'NOTES' in dataset.keys():
        dataset['NOTES'] += '\nTime-Sorted\n'
    else: 
        dataset['NOTES'] = 'Time-Sorted\n'
    
    if data_type == 'all':
        data_type = ['EC','MS']
    elif type(data_type) is str:
        data_type = [data_type]

    sort_indeces = {} #will store sort indeces of the time variables
    data_cols = dataset['data_cols'].copy()
    dataset['data_cols'] = []
    for col in data_cols:
        if vverbose:
            print('working on ' + col)
        data = dataset[col] #do I need the copy?
        if get_type(col) in data_type: #retuns 'EC' or 'MS', else I don't know what it is.
            timecol = get_timecol(col, verbose=vverbose)
            if timecol in sort_indeces.keys():
                indeces = sort_indeces[timecol]
            else:
                if verbose:
                    print('getting indeces to sort based on ' + timecol)
                indeces = np.argsort(dataset[timecol])
                sort_indeces[timecol] = indeces
            if len(data) != len(indeces):
                if vverbose:
                    print(col + ' is not the same length as its time variable!\n' +
                          col + ' will not be included in the time-sorted dataset.')
            else:
                dataset[col] = data[indeces]
                dataset['data_cols'] += [col]
                if verbose:
                    print('sorted ' + col + '!')
        else: #just keep it without sorting.
            dataset['data_cols'] += [col]
            dataset[col] = data
            

    if verbose:
        print('\nfunction \'sort_time\' finished!\n\n')    
    
    #return dataset#, sort_indeces  #sort indeces are useless, 17J11
    #if I need to read the return for normal use, then I don't want sort_indeces
    return dataset
    



def time_cal(data, ref_data=None, points=[(0,0)], point_type=['time', 'time'], 
             timecol='t', pseudotimecol=None, reftimecol='time/s', verbose=True):
    '''
    Calibrates the time column of a dataset according to sync points with a 
    reference dataset. tstamps are never changed.
    ------- inputs ---------
        data: the dataset for which to calibrate a timecolumn
        ref_data: the reference dataset.
        points: pairs of corresponding times or indeces in data and ref_data. 
    If only one point is given, time is calibrated just by a linear shift. If
    two or more are given, time is calibrated by the linear transformation best
    fitting the the calibration points (exact for two). 
        sync_type: Tuple specifying the mode of reference used in points, first
    for data and then for ref_data. Options are 'time', in which case the reference
    is to the actual value of the uncalibrated/reference time; and 'index' in 
    which case it is to the datapoint number of uncalibrated/reference time vector.
        timecol: the name of the column of data into which to save the calibrated time
        pseudotimecol: the name of the column of data containing the uncalibrated time.
    By default pseudotime is taken to be the same as time, i.e. the uncalibrated
    time is overwritten by the calibrated time.
        reftimecol: the name of the column of ref_data containing the reference time.
        verbose: True if you want the function to talk to you, useful for catching
    your mistakes and my bugs. False if you want a clean terminal or stdout.
    ------- output --------
        data: same as the input data, but with the calibrated time saved in the
    specified column.
    '''
    if verbose:
        print('\n\nfunction \'time_cal\' at your service!\n')
    
    if type(points[0]) not in [list, tuple]:
        points = [points]
    if type(point_type) is str:
        point_type = (point_type, point_type)
    
    t_vecs = np.zeros([2, len(points)]) # this is easiest if I pre-allocate an array
    mask = np.array([True for point in points]) # to record if a poitn has problems
    
    
    if ref_data in ['absolute', 'epoch', None]:
        ref_data = {reftimecol:None, 'tstamp':0} 
        #this is enough to keep the loop from crashing
        print('time calbration referenced to absolute time! point_type[1] must be \'time\'.')
    if 'tstamp' not in ref_data:
        offset_0 = 0
        print('No ref_data given or no ref_data[\'tstamp\']. ' + 
              'Assuming reference times are relative to the same tstamp!')
    else:
        offset_0 = ref_data['tstamp'] - data['tstamp']
        if verbose:
            print('tstamp offset = ' + str(offset_0))
        
    for i, t in enumerate([data[pseudotimecol], ref_data[reftimecol]]):    
        # this loop will go through twice. First for time from data, then
        # for the reftime from refdata. sync_type is a vector of two corresponding
        # to these two iterations, as is each point of points.
        
        #check the input
        if not point_type[i] in ['time', 'index', 'timestamp']:
            print('WARNING: Don\'t know what you mean, dude, when you say ' + 
                  str(point_type[i]) + '. Options for point_type[' + str(i) +
                  '] are \'index\', \'time\',  and \'timestamp\'.' +
                  ' Gonna try and guess from the first point of points.')
            if type(points[0][i]) is int:
                point_type[i] = 'index'
            elif type(points[0][i]) is float:
                point_type[i] = 'time'
            elif type(points[0][i]) is str:
                point_type[i] = 'timestamp'

        #get the times corresponding to the syncpoints into the array
        for j, point in enumerate(points):
            #print('point_type[' + str(i) + '] = ' + str(point_type[i])) #debugging
            try:
                if point_type[i] == 'index':
                    t_vecs[i][j] = t[point[i]]
                elif point_type[i] == 'time':
                    t_vecs[i][j] = point[i]
                elif point_type[i] == 'timestamp':
                    t_vecs[i][j] = timestamp_to_seconds(point[i])
            except (IndexError, TypeError) as e:
                print(str(e) + ' at point ' + str(point) + ' of ' +str(i) + ' (0=data, 1=refdata)')
                mask[j] = False
    
    N_good = len(mask[mask])
    
    if verbose:
        print('Got ' + str(N_good) + ' out of ' + str(len(points)) + ' points!') 
        # looks silly, but len(mask[mask]) easy way to get the number of True in mask
    
    
    if N_good == 1:
        offset = t_vecs[:, mask][1][0] - t_vecs[:, mask][0][0]
        if verbose:
            print('offset with respect to ref tstamp = ' + str(offset))
            print('total offset = ' + str(offset + offset_0))
        data[timecol] = data[pseudotimecol] + offset + offset_0
    
    else:
        t, t_ref = t_vecs[:, mask]  # this drops any point that had a problem
        #print(t_vecs)
        pf = np.polyfit(t, t_ref, 1)
        #print(pf)
        if verbose:
            print('with respect to ref tstamp:')
            print('time = ' + str(pf[0]) + ' * pseudotime + ' + str(pf[1]))
            print('with respect to tstamp:')
            print('time = ' + str(pf[0]) + ' * pseudotime + ' + str(pf[1] + offset_0))
        data[timecol] = pf[0] * data[pseudotimecol] + pf[1] + offset_0

    if time not in data['data_cols']:
        data['data_cols'] += [timecol] # otherwise synchronizing later can give error
    
    if verbose:
        print('\nfunction \'time_cal\' finished!\n\n')
    return data

def trigger_times(x, y, threshhold=2.5, triggergap=True):
    '''
    '''
    trigger_on = y > threshhold
    trigger_on_down = np.append(False, trigger_on[0:-1])
    trigger_start = np.logical_and(trigger_on, np.logical_not(trigger_on_down))
    
    if triggergap: # September 2018, noticed that MS isn't logging while trigger is on, leaving a gap.
        x_up = np.append(x[1:], x[-1])
        gap_start = x < x_up - 2
        trigger_start = np.logical_or(trigger_start, gap_start)
    times = x[trigger_start]
    return times

def get_trigger_times(data, xcol=None, ycol=None, label='Analog In', threshhold=2.5):
    from .Data_Importing import get_xy
    x, y = get_xy(data, xcol, ycol, label)
    triggers = trigger_times(x, y, threshhold=threshhold)
    data['triggers'] = triggers
    return triggers


def trigger_cal(data, triggers=None, pseudotimecol=None, pt_str=None, 
                t_str=None, timecol=None, shiftcol='selector', edge=2, 
                verbose=True):
    '''
    data is the only required argument, given that the trigger times are
    stored in data['triggers'], as they are after a call to get_trigger_times(data).
    
    By default data['time/s'] is adjusted linearly to line up triggers with
    changes in data['loop number'] and data['file number'] and stored as
    data['time/s*'], which is subsequently used by other functions.
    
    More generally, this function:
    
    Calibrates a time column in the dataset given by pt_str or pseudotimecol
    according to a list of triggers, which are assumed to come at times where 
    another column, given by shiftcol, changes.
    Thre does not need to be a trigger for every change in data[shiftcol], but
    there should be a change in data[shiftcol] at every trigger time. The 
    function shouldn't trip up so long as this is satisfied and the time between
    adjacent triggers is much larger than the needed correction in the time.
    
    The calibrated time is stored in the column given by t_str or timecol. The
    name of the calibrated time column is stored as data['t_str'] for plotting 
    functions to refer to by default. The name of the uncalibrated time column
    is stored as data['pt_str'].
    
    By default shiftcol points to a custom 'selector' column which, if not
    defined prior to calling this function, is defined here as a linear 
    combination of file number, loop number, and cycle number weighted oddly
    to keep values unique. Triggers are assumed to correspond to changes in 
    this column.
    
    '''
    if verbose:
        print('\n\nfunction \'trigger cal\' at your service!\n')
    
    # first, parse inputs. This means figuring out where in the data the
    # uncalibrated time data is, i.e. data[pt_str],
    # then figure out where the calibrated data should go, i.e. data[t_str]
    # t_str is synonymous with timecol. pt_str is synonymous with pseudotimecol
    # This is thus a mixture of old notation (i.e. sync_metadata with V_str etc)
    # and new notation (i.e. time_cal with timecol etc)
    
    if pt_str is None and 'pt_str' in data:
        pt_str = data['pt_str']
    if t_str is None and 't_str' in data:
        t_str = data['t_str']
    
    if pseudotimecol is None:
        if pt_str is not None:
            pseudotimecol = pt_str
        elif t_str is not None:
            pseudotimecol = t_str
        else:
            pseudotimecol = 'time/s'
    
    if timecol is None:
        if pseudotimecol == t_str:
            timecol = pseudotimecol + '*'
            t_str = timecol
        elif t_str is not None:
            timecol = t_str
        else:
            timecol = pseudotimecol + '*'
            
    if triggers is None:
        if 'triggers' not in data:
            get_trigger_times(data)
        triggers = data['triggers']
    
    if type(triggers) is not np.ndarray:
        if triggers in [list, tuple]:
            triggers = np.array(triggers)
        else:
            triggers = np.array([triggers])
    
    pt = data[pseudotimecol].copy()
    
    # set up the selector column to use for shift data
    if shiftcol == 'selector' and 'selector' not in data:
        from .EC import make_selector
        make_selector(data)
    
    # ---- check if there are triggers in the set and in the time interval ----
    if len(triggers) == 0:
        if verbose:
            print('There are no triggers in this data set! No calibration. Finished!')
        return pseudotimecol
    
    if verbose:
        print(str(len(triggers)) + ' triggers spanning t= ' + str(triggers[0]) +
              ' to ' + str(triggers[-1]))
    triggermask = np.logical_and(pt[0]-edge<triggers, triggers<pt[-1]+edge)
    triggers = triggers[triggermask]
    if len(triggers)==0:
        print('no triggers in time range. can\'t calibrate.')
        data['t_str'] = pseudotimecol
        return pseudotimecol
    if verbose:
        print('... of which ' + str(len(triggers)) + ' are between t= ' +
              str(pt[0]-edge) + ' and ' + str(pt[-1]+edge) + '.')
    
    if shiftcol not in data:
        if verbose:
            print('no column \'' + shiftcol + '\' in dataset.')
            if len(triggers) == 1:
                print('Assuming the trigger is the start of the file.')
            else:
                print('Assuming the first trigger is the start of the file, \n' +
                      '... and ignoring subsequent triggers.')
        offset = triggers[0] - pt[0]
        data[timecol] = pt + offset
        data['pt_str'] = pseudotimecol
        data['t_str'] = timecol
        return timecol
        
    
    # ----- find the times at which data[shiftcol] changes value ----
    shiftvalue = data[shiftcol]
    shiftvalue_down = np.append(shiftvalue[0]-1, shiftvalue[:-1])
    shiftmask = np.logical_not(shiftvalue == shiftvalue_down)
    print('shiftmask.shape = \n' + str(shiftmask.shape) + '\npt.shape = \n' + str(pt.shape)) # debugging
    shifttimes = pt[shiftmask]        
    
    # ----- get vectors of trigger times and corresponding shift times -----
    pt_points = np.array([])  #pseutodimes, corresponding to shifts in data[shiftcolumn]
    pt_indeces = np.array([]) #indeces of the pseudotimes (to check for duplicates)
    t_points = np.array([])   #times, corresponding to trigger times
    for trigger in triggers:
        #find the shift_time closest to it:
        err = abs(shifttimes - trigger)
        index = np.argmin(err)
        pt_point = shifttimes[index]
        if err[index]>edge and verbose:
            print('Large offset between matched trigger at ' + str(trigger) + 
                  ' and ' + shiftcol + ' change at ' + str(pt_point) + '!')
        #Check if that shift_time has already been linked to a trigger
        if index in pt_indeces:
            if verbose:
                print('Multiple triggers seem to correspond to the file start at ' +
                      str(pt_point) + '. I\'ll assume the first ones ' + 
                      'were false starts and just keep the last one.')
            pt_points[pt_indeces==index] = pt_point # if so, use tghe new shift_time
        else: #otherwise add it to the vectors.
            pt_points = np.append(pt_points, pt_point)
            pt_indeces = np.append(pt_indeces, index)
            t_points = np.append(t_points, trigger)
    
    print('matched ' + str(len(pt_points)) + ' triggers to shifts in ' + shiftcol + '.')
    
    t = pt.copy()  #get ready to build the new time variable
    # points before the trigger should be shifted so the first trigger matches
    startmask = pt <= pt_points[0]
    if np.any(startmask):
        startoffset = t_points[0] - pt_points[0]
        if verbose:
            print('shifting start point(s) by ' + str(startoffset) + '.')
            #print(len(np.where(startmask))) #debugging 
            # turns out it's always exactly 1 point, of course
        t[startmask] = pt[startmask] + startoffset
    # points between the first and last trigger should be interpolated according to the triggers
    middlemask = np.logical_and(pt_points[0]<pt, pt<pt_points[-1])
    if np.any(middlemask):
        if verbose:
            print('interpolating to trigger times between t= ' 
                  + str(t_points[0]) + ' and ' + str(t_points[-1]) + '.')
        t[middlemask] = np.interp(pt[middlemask], pt_points, t_points)
    # points after the last trigger should be shifted so the last trigger matches
    endmask = pt_points[-1] <= pt
    if np.any(endmask):
        endoffset = t_points[-1] - pt_points[-1]
        if verbose:
            print('shifting end points by ' + str(endoffset) + '.')
        t[endmask] = pt[endmask] + endoffset
        
    data[timecol] = t
    
    data['t_str'] = timecol
    data['pt_str'] = pseudotimecol
    if timecol not in data['data_cols']:
        data['data_cols'] += [t_str]
    if pseudotimecol not in data['data_cols']:
        data['data_cols'] += [pt_str]
    if verbose:
        print('\nfunction \'trigger cal\' finished!\n\n')
    return timecol

           
    
