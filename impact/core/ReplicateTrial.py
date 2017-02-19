# coding=utf-8

import numpy as np
import dill as pickle
import pandas as pd
from .SingleTrial import SingleTrial
from .AnalyteData import TimeCourse
from .TrialIdentifier import TrialIdentifier
import copy
from scipy import stats
import matplotlib.pyplot as plt
from .settings import settings
default_outlier_cleaning_flag = settings.default_outlier_cleaning_flag
max_fraction_replicates_to_remove = settings.max_fraction_replicates_to_remove
verbose = settings.verbose


from ..database import Base
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, PickleType, Float
from sqlalchemy.orm import relationship
from sqlalchemy.orm.collections import attribute_mapped_collection

class ReplicateTrial(Base):
    """
    This object stores SingleTrial objects and calculates statistics on these replicates for each of the
    titers which are stored within it
    """

    __tablename__ = 'replicate_trial'

    id = Column(Integer, primary_key=True)

    avg_id = Column(Integer,ForeignKey('single_trial.id'))
    avg = relationship('SingleTrial', uselist=False, foreign_keys=[avg_id])

    std_id = Column(Integer,ForeignKey('single_trial.id'))
    std = relationship('SingleTrial', uselist=False, foreign_keys=[std_id])

    single_trial_dict = relationship('SingleTrial',
                                     collection_class = attribute_mapped_collection('keyword'),
                                     foreign_keys = 'SingleTrial.parent_id')

    trial_identifier_id = Column(Integer,ForeignKey('trial_identifier.id'))
    trial_identifier = relationship('TrialIdentifier')

    stage_parent_id = Column(Integer,ForeignKey('replicate_trial.id'))
    stages = relationship('ReplicateTrial')

    blank_id = Column(Integer,ForeignKey('single_trial.id'))
    blank = relationship('SingleTrial',uselist=False, foreign_keys=[blank_id])

    parent = relationship('Experiment')
    parent_id = Column(Integer,ForeignKey('experiment.id'))

    bad_replicates = Column(PickleType)
    replicate_ids = Column(PickleType)
    # replicate_df = Column(PickleType)

    def __init__(self):
        self.avg = SingleTrial()
        self.std = SingleTrial()
        self.t = None

        self.single_trial_dict = {}

        self.trial_identifier = TrialIdentifier()
        self.bad_replicates = []
        self.replicate_ids = []
        self.replicate_df = dict()

        self.outlier_cleaning_flag = default_outlier_cleaning_flag

        self.stages = []

        # self.blank = SingleTrial()

    def calculate(self):
        for single_trial_key in self.single_trial_dict:
            self.single_trial_dict[single_trial_key].calculate()

        if self.blank:  self.substract_blank()
        self.calculate_statistics()

    def serialize(self):
        serialized_dict = {}

        for replicate_id in self.single_trial_dict:
            serialized_dict[str(replicate_id)] = self.single_trial_dict[replicate_id].serialize()
        serialized_dict['avg'] = self.avg.serialize()
        serialized_dict['std'] = self.std.serialize()
        import json
        return json.dumps(serialized_dict)

    def calculate_stages(self, stage_indices=None):
        if stage_indices is None:
            raise Exception('No stage_indices provided')

        self.stages = []
        self.stage_indices = stage_indices

        for stage_bounds in stage_indices:
            temp_stage = self.create_stage(stage_bounds)
            temp_stage.calculate()
            self.stages.append(temp_stage)

    def create_stage(self, stage_bounds):
        stage = ReplicateTrial()
        for replicate_id in self.single_trial_dict:
            # if self.blank:
            #     blank_stage = self.blank.create_stage(stage_bounds)
            #     stage.set_blank(blank_stage)
            single_trial = self.single_trial_dict[replicate_id]
            stage.add_replicate(single_trial.create_stage(stage_bounds))

        return stage

    def summary(self):
        return

    def get_normalized_data(self, normalize_to):
        new_replicate = ReplicateTrial()
        for replicate_id in self.single_trial_dict:
            single_trial = self.single_trial_dict[replicate_id]
            single_trial.normalize_data(normalize_to)
            new_replicate.add_replicate(single_trial)
        self = new_replicate

    def check_replicate_unique_id_match(self):
        """
        Ensures that the uniqueIDs match for all te replicate_id experiments
        """
        replicate_ids = list(self.single_trial_dict.keys())
        replicate_ids.sort()
        for i in range(len(self.single_trial_dict) - 1):
            if self.single_trial_dict[replicate_ids[i]].trial_identifier.unique_replicate_trial() \
                    != self.single_trial_dict[replicate_ids[i + 1]].trial_identifier.unique_replicate_trial():
                raise Exception(
                    "the replicates do not have the same uniqueID, either the uniqueID includes too much information or the strains don't match")

            # Deprecated as of v0.5.0, pandas allows dealing with data with different shapes
            # if (self.single_trial_list[i].t != self.single_trial_list[i + 1].t).all():
            #     print(self.single_trial_list[i].t, self.single_trial_list[i + 1].t)
            #     raise Exception("time vectors don't match within replicates")
            # else:
            #     self.t = self.single_trial_list[i].t

                # if len(self.single_trial_list[i].t) != len(self.single_trial_list[i + 1].t):  # TODO
                #     print("Time Vector 1: ", self.single_trial_list[i].t, "\nTime Vector 2: ", self.single_trial_list[i + 1].t)
                #     print("Vector 1: ", self.single_trial_list[i].substrate.data_vector, "\nVector 2: ",
                #           self.single_trial_list[i + 1].substrate.data_vector)
                #     raise (Exception("length of substrate vectors do not match"))
                #
                # for key in self.single_trial_list[i].products:
                #     if len(self.single_trial_list[i].products[key].data_vector) != len(
                #             self.single_trial_list[i + 1].products[key].data_vector):
                #         raise (Exception("length of product vector " + str(key) + " do not match"))

    def add_replicate(self, singleTrial):
        """
        Add a SingleTrial object to this list of replicates

        Parameters
        ----------
        singleTrial : :class:`~SingleTrial`
            Add a SingleTrial
        """
        from .settings import settings
        live_calculations = settings.live_calculations

        if singleTrial.trial_identifier.replicate_id is None:
            singleTrial.trial_identifier.replicate_id = 1

        # Get info from single trial
        self.single_trial_dict[str(singleTrial.trial_identifier.replicate_id)] = singleTrial
        if len(self.single_trial_dict) == 1:
            self.t = self.single_trial_dict[str(singleTrial.trial_identifier.replicate_id)].t
        self.check_replicate_unique_id_match()


        self.trial_identifier = copy.copy(singleTrial.trial_identifier)
        self.trial_identifier.time = None
        if singleTrial.trial_identifier.replicate_id not in self.replicate_ids:
            self.replicate_ids.append(
                singleTrial.trial_identifier.replicate_id)  # TODO remove this redundant functionality
        else:
            raise Exception('Duplicate replicate id: '
                            + str(singleTrial.trial_identifier.replicate_id)
                            + '.\nCurrent ids: '
                            + str(self.replicate_ids))
        try:
            self.replicate_ids.sort()
        except Exception as e:
            print(e)
            print(self.replicate_ids)
            raise Exception(e)
        if live_calculations:
            self.calculate_statistics()

    def calculate_statistics(self):
        """
        Calculates the statistics on the SingleTrial objects
        """
        # Features
            # yield
            # specific_productivity
            # raw




        unique_analytes = self.get_analytes()




        # Calculate single trial statistics (mass balance)


        # Calculate analyte statistics
            # for feature in features
                # for analyte in unique_analytes:
                    # combined_df = pd.DataFrame()
                    # Build a df
                    # Add the dfs

            # pd_series
            # yields
            # specific productivity

        # feature_list = []
        # for feature in feature_list:
        #     for analyte in unique_analytes:
        #         self.replicate_df[analyte] = pd.DataFrame()
        #
        #         # Only iterate through single trials with the analyte of interest
        #         temp_single_trial_dict = {str(replicate_id):self.single_trial_dict[replicate_id]
        #                                   for replicate_id in self.single_trial_dict
        #                                   if analyte in self.single_trial_dict[replicate_id].analyte_dict}
        #
        #         try:
        #             temp_analyte_df = pd.DataFrame(
        #                 {replicate_id: getattr(temp_single_trial_dict[replicate_id].analyte_dict[analyte],feature.name)
        #                  for replicate_id in temp_single_trial_dict})
        #         except ValueError as e:
        #             print({replicate_id: getattr(temp_single_trial_dict[replicate_id].analyte_dict[analyte],feature.name)
        #                  for replicate_id in temp_single_trial_dict})
        #             raise ValueError(e)
        #
        #     for analyte in unique_analytes:
        #         for stat, calc in zip(['avg', 'std'], [np.mean, np.std]):
        #             getattr(self, stat).analyte_dict[analyte] = TimeCourse()
        #
        #             # Save the mean or std
        #             if stat == 'avg':
        #                 getattr(self, stat).analyte_dict[analyte].pd_series = self.replicate_df[analyte].mean(
        #                     axis=1)
        #             elif stat == 'std':
        #                 getattr(self, stat).analyte_dict[analyte].pd_series = self.replicate_df[analyte].std(axis=1)
        #             else:
        #                 raise Exception('Unknown statistic type')


        # Build a df for all analytes on the same index
        for analyte in unique_analytes:
            # Build the df from all the replicates
            self.replicate_df[analyte] = pd.DataFrame()

            # Only iterate through single trials with the analyte of interest
            temp_single_trial_dict = {str(replicate_id):self.single_trial_dict[replicate_id]
                                      for replicate_id in self.single_trial_dict
                                      if analyte in self.single_trial_dict[replicate_id].analyte_dict}

            try:
                temp_analyte_df = pd.DataFrame(
                    {replicate_id: temp_single_trial_dict[replicate_id].analyte_dict[analyte].pd_series
                     for replicate_id in temp_single_trial_dict})
            except ValueError as e:
                print({replicate_id: temp_single_trial_dict[replicate_id].analyte_dict[analyte].pd_series
                     for replicate_id in temp_single_trial_dict})
                raise ValueError(e)

            # Merging the dataframes this way will allow different time indices for different analytes
            self.replicate_df[analyte] = pd.merge(self.replicate_df[analyte],
                                                  temp_analyte_df,
                                                  left_index=True,
                                                  right_index=True,
                                                  how='outer')

            self.prune_bad_replicates(analyte)

        for analyte in unique_analytes:
            for stat, calc in zip(['avg', 'std'], [np.mean, np.std]):
                getattr(self, stat).analyte_dict[analyte] = TimeCourse()

                # Save the mean or std
                if stat == 'avg':
                    getattr(self, stat).analyte_dict[analyte].pd_series = self.replicate_df[analyte].mean(axis=1)
                elif stat == 'std':
                    getattr(self, stat).analyte_dict[analyte].pd_series = self.replicate_df[analyte].std(axis=1)
                else:
                    raise Exception('Unknown statistic type')

                # If a fit_params exists, calculate the mean
                if None not in [self.single_trial_dict[replicate_id].analyte_dict[analyte].fit_params
                                for replicate_id in self.single_trial_dict]:
                    temp = dict()
                    for param in self.single_trial_dict[list(self.single_trial_dict.keys())[0]].analyte_dict[analyte].fit_params:
                        temp[param] = calc(
                            [self.single_trial_dict[replicate_id].analyte_dict[analyte].fit_params[param]
                             for replicate_id in self.single_trial_dict
                             if self.single_trial_dict[replicate_id].trial_identifier.replicate_id not in self.bad_replicates])

                    getattr(self, stat).analyte_dict[analyte].fit_params = temp
                else:
                    print([self.single_trial_dict[replicate_id].analyte_dict[analyte].fit_params
                                for replicate_id in self.single_trial_dict])


                getattr(self, stat).analyte_dict[analyte].trial_identifier = \
                    self.single_trial_dict[list(self.single_trial_dict.keys())[0]].analyte_dict[analyte].trial_identifier


        # Get all unique yields
        unique_yields = []
        for replicate_id in self.single_trial_dict:
            single_trial = self.single_trial_dict[replicate_id]
            for analyte in single_trial.yields:
                unique_yields.append(analyte)
        unique_yields = list(set(unique_analytes))

        # Calculate statistics for each yield
        for analyte in unique_yields:
            temp_single_trial_dict = {replicate_id: self.single_trial_dict[replicate_id] for replicate_id in self.single_trial_dict if
                                      analyte in self.single_trial_dict[replicate_id].yields}
            yield_df = pd.DataFrame()

            for replicate_id in temp_single_trial_dict:
                single_trial = temp_single_trial_dict[replicate_id]
                temp_yield_df = pd.DataFrame({single_trial.trial_identifier.replicate_id: single_trial.yields[analyte]})
                yield_df = pd.merge(yield_df,
                                    temp_yield_df,
                                      left_index=True,
                                      right_index=True,
                                      how='outer')

            # Save the mean or std
            self.avg.yields[analyte] = np.array(yield_df.mean(axis=1))
            self.std.yields[analyte] = np.array(yield_df.std(axis=1))

    def get_analytes(self):
        # Get all unique analytes
        unique_analytes = []
        for replicate_id in self.single_trial_dict:
            single_trial = self.single_trial_dict[replicate_id]
            for titer in single_trial.analyte_dict:
                unique_analytes.append(titer)
        unique_analytes = list(set(unique_analytes))
        return unique_analytes

    def prune_bad_replicates(self, analyte):  # Remove outliers
        from .settings import settings
        verbose = settings.verbose
        max_fraction_replicates_to_remove = settings.max_fraction_replicates_to_remove
        outlier_cleaning_flag = settings.outlier_cleaning_flag

        # http://stackoverflow.com/questions/23199796/detect-and-exclude-outliers-in-pandas-dataframe
        df = self.replicate_df[analyte]
        col_names = list(df.columns.values)
        backup = self.replicate_df[analyte]

        if outlier_cleaning_flag and len(col_names) > 2:
            outlier_removal_method = 'iterative_removal'
            # Method one for outlier removal
            if outlier_removal_method == 'z_score':
                fraction_outlier_pts = np.sum(np.abs(stats.zscore(df)) < 1, axis=0) / len(df)
                print(fraction_outlier_pts)
                bad_replicates = [col_name for i, col_name in enumerate(col_names) if fraction_outlier_pts[i] < 0.8]
                # good_replicates = (np.abs(stats.zscore(df)) < 3).all(axis=0)  # Find any values > 3 std from mean
                # if bad_replicates.any():
                print(bad_replicates)
                if bad_replicates != []:
                    good_replicate_cols = [col_names[x] for x, col_name in enumerate(bad_replicates)
                                           if col_name not in bad_replicates]
                else:
                    good_replicate_cols = col_names
                bad_replicate_cols = [col_names[x] for x, col_name in enumerate(bad_replicates)
                                      if col_name in bad_replicates]
                print('good', good_replicate_cols)
                print('bad: ', bad_replicate_cols)

            # method 2 for outlier removal (preferred)
            # this method removal each replicate one by one, and if the removal of a replicate reduces the std
            # by a certain threshold, the replicate is flagged as removed
            if outlier_removal_method == 'iterative_removal':
                bad_replicate_cols = []
                good_replicate_cols = []

                # Determine the max number of replicates to remove
                for _ in range(int(len(df) * max_fraction_replicates_to_remove)):
                    # A value between 0 and 1, > 1 means removing the replicate makes the yield worse
                    std_deviation_cutoff = 0.1
                    # df = pd.DataFrame({key: np.random.randn(5) for key in ['a', 'b', 'c']})
                    temp_std_by_mean = {}
                    for temp_remove_replicate in list(df.columns.values):
                        indices = [replicate for i, replicate in enumerate(df.columns.values) if
                                   replicate != temp_remove_replicate]
                        temp_remove_replicate_df = df[indices]
                        temp_mean = temp_remove_replicate_df.mean(axis=1)
                        temp_std = temp_remove_replicate_df.std(axis=1)
                        temp_std_by_mean[temp_remove_replicate] = np.mean(abs(temp_std / temp_mean))

                    temp_min_val = min([temp_std_by_mean[key] for key in temp_std_by_mean])
                    if temp_min_val < std_deviation_cutoff:
                        bad_replicate_cols.append([key for key in temp_std_by_mean if temp_std_by_mean[key] == temp_min_val][0])

                    good_replicate_cols = [key for key in temp_std_by_mean if key not in bad_replicate_cols]
                    df = df[good_replicate_cols]
            self.replicate_df[analyte] = df[good_replicate_cols]

            # Plot the results of replicate removal
            if verbose:
                plt.figure()
                try:
                    if good_replicate_cols != []:
                        plt.plot(backup[good_replicate_cols], 'r')
                    if bad_replicate_cols != []:
                        plt.plot(backup[bad_replicate_cols], 'b')
                    plt.title(self.trial_identifier.unique_replicate_trial())
                except Exception as e:
                    print(e)
            del backup

    def set_blank(self, replicate_trial):
        self.blank = replicate_trial

    def substract_blank(self):
        # Check which analytes have blanks defined
        analytes_with_blanks = self.blank.get_analytes()

        # Remove from each analyte and then redo calculations
        self.blank_subtracted_analytes = []

        # for blank_analyte in analytes_with_blanks:
        for single_trial_key in self.single_trial_dict:
            single_trial = self.single_trial_dict[single_trial_key]
            for blank_analyte in analytes_with_blanks:
                single_trial.analyte_dict[blank_analyte].data_vector = \
                    single_trial.analyte_dict[blank_analyte].data_vector \
                    - self.blank.avg.analyte_dict[blank_analyte].data_vector

        self.blank_subtracted_analytes.append(blank_analyte)

    def get_unique_analytes(self):
        return list(set([analyte
                         for single_trial_key in self.single_trial_dict
                         for analyte in self.single_trial_dict[single_trial_key].analyte_dict]
                        )
                    )