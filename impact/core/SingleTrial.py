import numpy as np
import dill as pickle
import pandas as pd
import sqlite3 as sql
import warnings
import copy

from .TrialIdentifier import TrialIdentifier
from .AnalyteData import TimeCourse, TimePoint

from django.db import models
from ..database import Base
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, PickleType, Float
from sqlalchemy.orm import relationship
from sqlalchemy.orm.collections import attribute_mapped_collection

class SingleTrial(Base):
    """
    Container for :class:`~TiterObject` to build a whole trial out of different measurements. E.g. one flask would
    contain data for biomass (OD), products (ethanol, acetate), substrates (glucose), fluorescence (gfpmut3, mCherry)
    """

    __tablename__ = 'single_trial'

    id = Column(Integer, primary_key=True)

    trial_identifier_id = Column(Integer,ForeignKey('trial_identifier.id'))
    _trial_identifier = relationship('TrialIdentifier')

    analyte_dict = relationship('TimeCourse',
                                collection_class = attribute_mapped_collection('analyte_name'),
                                cascade = 'save-update, delete')


    # analyte_df = Column(PickleType)
    # yield_time_points = relationship('YieldTimePoint')
    # normalized_data_time_points = relationship('NormalizedTimePoint')
    # yields_df = Column(PickleType)

    _substrate_name = Column(PickleType)
    product_names = Column(PickleType)
    biomass_name = Column(PickleType)
    stage_indices = Column(PickleType)

    parent_id = Column(Integer, ForeignKey('replicate_trial.id'))

    stage_parent_id = Column(Integer, ForeignKey('single_trial.id'))
    stages = relationship('SingleTrial', foreign_keys = 'SingleTrial.stage_parent_id')

    normalized_data = Column(PickleType)

    def __init__(self):
        # Trial identifier with relevant features common to the trial
        self._trial_identifier = None

        # Analyte objects
        self.analyte_dict = dict()

        # Dataframe containing all of the analytes with a common index
        self.analyte_df = pd.DataFrame()

        # Dict and df containing yields for each product
        self.yields = dict()
        self.yields_df = pd.DataFrame()

        # Contains the names of different analyte types
        # self._substrate_name = None
        # self.product_names = []
        # self.biomass_name = None

        # Contains information about the stages used in the experiment, TODO
        self.stage_indices = None
        self.stage_list = None

        # Data normalized to different features, not serialized
        self.normalized_data = dict()

        self.features = []
        self.analytes_to_features = {}
        self.analyte_types = ['biomass','substrate','product']
        for analyte_type in self.analyte_types:
            self.analytes_to_features[analyte_type] = []

        self.register_feature(ProductYieldFactory())
        self.register_feature(SpecificProductivityFactory())
        # self.register_feature()

    def register_feature(self, feature):
        self.features.append(feature)
        analyte_types = ['biomass','substrate','product']
        for analyte_type in analyte_types:
            if analyte_type in feature.requires:
                self.analytes_to_features[analyte_type].append(feature)


    def serialize(self):
        serialized_dict = {}

        if self.trial_identifier:
            serialized_dict['strain_id'] = self.trial_identifier.strain.name
            serialized_dict['id_1'] = self.trial_identifier.id_1
            serialized_dict['id_2'] = self.trial_identifier.id_2

        for analyte_name in self.analyte_dict:
            serialized_dict[analyte_name] = self.analyte_dict[analyte_name].serialize()

        serialized_dict['yields'] = self.yields_df.to_json()

        return serialized_dict

    # Setters and Getters
    @property
    def stages(self):
        return self._stages

    @stages.setter
    def stages(self, stages):
        """
        Creates stages when they are defined

        Parameters
        ----------
        stages : list of stage start and end lists [start_index, end_index]

        """
        self._stages = stages

        for stage in stages:
            stage = self.create_stage(stage)
            self.stage_list.append(stage)

    @property
    def substrate_name(self):
        return [str(self.analyte_dict[key].trial_identifier.analyte_name)
                for key in self.analyte_dict
                if self.analyte_dict[key].trial_identifier.analyte_type == 'substrate'][0]

    @property
    def product_names(self):
        return [str(self.analyte_dict[key].trial_identifier.analyte_name)
                for key in self.analyte_dict
                if self.analyte_dict[key].trial_identifier.analyte_type == 'product'][0]

    @property
    def biomass_name(self):
        return [str(self.analyte_dict[key].trial_identifier.analyte_name)
                for key in self.analyte_dict
                if self.analyte_dict[key].trial_identifier.analyte_type == 'biomass'][0]

    # @substrate_name.setter
    # def substrate_name(self, substrate_name):
    #     self._substrate_name = substrate_name
    #     self.calculate_substrate_consumed()
    #     if len(self.product_names) > 0:
    #         self.calculate_yield()

    @property
    def t(self):
        return self._t

    @t.setter
    def t(self, t):
        self._t = t

    # @property
    # def products(self):
    #     return self._products
    #
    # @products.setter
    # def products(self, products):
    #     self._products = products
    #     if self._substrate:
    #         self.calculate_yield()

    @property
    def trial_identifier(self):
        return self._trial_identifier

    @trial_identifier.setter
    def trial_identifier(self, trial_identifier):
        self._trial_identifier = trial_identifier

        self.analyte_name = trial_identifier.analyte_name

    def calculate(self):
        for analyte_key in self.analyte_dict:
            self.analyte_dict[analyte_key].calculate()

    def normalize_data(self, normalize_to):
        for product in self.product_names:
            self.normalized_data[product] = self.analyte_dict[product] / self.analyte_dict[normalize_to]

    def create_stage(self, stage_bounds):
        stage = SingleTrial()
        for titer in self.analyte_dict:
            stage.add_analyte_data(self.analyte_dict[titer].create_stage(stage_bounds))

        return stage

    def summary(self, print=False):
        summary = dict()

        for analyte_type in ['substrate','products','biomass']:
            summary[analyte_type] = [str(analyte_data) for analyte_data in self.analyte_dict if analyte_data.trial_identifier.analyte_type == analyte_type]
        summary['number_of_data_points'] = len(self._t)
        summary['run_identifier'] = self.trial_identifier.summary(['strain_id', 'id_1', 'id_2',
                                                                'replicate_id'])

        if print:
            print(summary)

        return summary

    def calculate_mass_balance(self, OD_gdw=None, calculateFBACO2=False):
        """
        Calculate a mass balance given the supplied substrate and products

        Parameters
        ----------
        OD_gdw : float
            The correlation betwen OD_gdw and OD600
        calculateFBACO2 : bool
            Flag to calculate the CO2 using FBA (not implemented yet)
        """
        # if calculateFBACO2:
        #     import cobra
        #
        #     # Load the COBRA model
        #     ...
        #
        #     # Convert the common names to COBRA model names
        #     commonNameCobraDictionary = {'Lactate'  : ...,
        #                                  'Ethanol'  : ...,
        #                                  'Acetate'  : ...,
        #                                  'Formate'  : ...,
        #                                  'Glycolate': ...,
        #                                  'Glucose'  : ...,
        #                                  'Succinate': ...
        #                                  }
        #
        #     # Get the molar mass from COBRA model and covert the grams to mmol
        #     substrate = model.metabolites.get_by_id(substrate_name)
        #     # substrate_mmol = substrate.formulaWeight()
        #     # substrate.lower_bound = self.substrate.data_vector[-1]
        #     # substrate.upper_bound = self.substrate.data_vector[-1]
        #     productsCOBRA = dict()
        #     for key in self.yields:
        #         modelMetID = commonNameCobraDictionary[key]
        #         productsCOBRA[key] = model.metabolites.get_by_id(modelMetID)
        #
        #     # Set the bounds
        #     ...
        #
        #     # Run the FBA and return the CO2
        #     ...

        if type(OD_gdw) == None:
            # Parameters for E. coli
            OD_gdw = 0.33  # Correlation for OD to gdw for mass balance

        # self.substrate_consumed

        if self.OD is not None:
            # Calc mass of biomass
            biomass_gdw = self._OD.data_vector / OD_gdw
        else:
            biomass_gdw = None

        # Calculate the mass of products consumed
        totalProductMass = np.sum([self.products[productKey].data_vector for productKey in self.products], axis=0)

        # Calculate the mass balance (input-output)
        if biomass_gdw is None:   biomass_gdw = np.zeros(
            [len(self.substrate_consumed)])  # If this isn't defined, set biomass to zero
        massBalance = self.substrate_consumed - totalProductMass - biomass_gdw

        return {'substrate_consumed': self.substrate_consumed,
                'totalProductMass' : totalProductMass,
                'biomass_gdw'      : biomass_gdw,
                'massBalance'      : massBalance}

    def calculate_ODE_fit(self):
        """
        WIP to fit the data to ODEs
        """
        biomass = self.analyte_dict[self.biomass_name].data_vector
        biomass_rate = np.gradient(self.analyte_dict[self.biomass_name].data_vector) / np.gradient(
            self.analyte_dict[self.biomass_name].time_vector)
        self.analyte_dict[self.substrate_name]
        self.analyte_dict[self.product_names]

        def dFBA_functions(y, t, rate):
            # Append biomass, substrate and products in one list
            exchange_reactions = biomass_flux + substrate_flux + product_flux
            # y[0]           y[1]
            dydt = []
            for exchange_reaction in exchange_reactions:
                if y[1] > 0:  # If there is substrate
                    dydt.append(exchange_reaction * y[0])
                else:  # If there is not substrate
                    dydt.append(0)
            return dydt

        import numpy as np
        from scipy.integrate import odeint

        # Let's assign the data to these variables
        biomass_flux = []
        biomass_flux.append(model.solution.x_dict[biomass_keys[0]])

        substrate_flux = []
        substrate_flux.append(model.solution.x_dict[substrate_keys[0]])

        product_flux = [model.solution.x_dict[key] for key in product_keys]

        exchange_keys = biomass_keys + substrate_keys + product_keys

        # Now, let's build our model for the dFBA
        def dFBA_functions(y, t, biomass_flux, substrate_flux, product_flux):
            # Append biomass, substrate and products in one list
            exchange_reactions = biomass_flux + substrate_flux + product_flux
            # y[0]           y[1]
            dydt = []
            for exchange_reaction in exchange_reactions:
                if y[1] > 0:  # If there is substrate
                    dydt.append(exchange_reaction * y[0])
                else:  # If there is not substrate
                    dydt.append(0)
            return dydt

        # Now let's generate the data
        sol = odeint(dFBA_functions, y0, t,
                     args=([flux * np.random.uniform(1 - noise, 1 + noise) for flux in biomass_flux],
                           [flux * np.random.uniform(1 - noise, 1 + noise) for flux in
                            substrate_flux],
                           [flux * np.random.uniform(1 - noise, 1 + noise) for flux in
                            product_flux]))

        dFBA_profile = {key: [row[i] for row in sol] for i, key in enumerate(exchange_keys)}

    def add_analyte_data(self, analyte_data):
        """
        Add a :class:`~TiterObject`

        Parameters
        ----------
        analyte_data : :class:`~TiterObject`
            A titer object to be added

        """
        from .settings import settings
        live_calculations = settings.live_calculations

        # Check if this analyte already exists
        if analyte_data.trial_identifier.analyte_name in self.analyte_dict:
            raise Exception('A duplicate titer was added to the single trial,\n'
                            'Make sure replicates are defined properly,\n'
                            'Duplicate TrialIdentifier: ',
                            vars(analyte_data.trial_identifier))

        # Set the parent
        analyte_data.parent = self

        self.analyte_dict[analyte_data.trial_identifier.analyte_name] = analyte_data

        # Add relevant analyte types to calculate features
        for feature in self.features:
            if analyte_data.trial_identifier.analyte_type in feature.requires:
                feature.add_analyte_data(analyte_data)

        # check if trial identifiers match TODO This needs updating.
        if self.trial_identifier is None:
            self.trial_identifier = TrialIdentifier()

            for attr in ['strain', 'id_1', 'id_2', 'replicate_id']:
                setattr(self.trial_identifier, attr, getattr(analyte_data.trial_identifier, attr))

        for attr in ['strain','id_1','id_2','replicate_id']:
            if str(getattr(self.trial_identifier,attr)) != str(getattr(analyte_data.trial_identifier, attr)):
                raise Exception('Trial identifiers do not match at the following attribute: '
                                + attr
                                +' val 1: '
                                + str(getattr(self.trial_identifier,attr))
                                +' val 2: '
                                + str(getattr(analyte_data.trial_identifier, attr)))
            # else:
            #     setattr(self.trial_identifier, attr, getattr(analyte_data.trial_identifier, attr))


        self.trial_identifier.time = None

        # Pandas support
        temp_analyte_df = pd.DataFrame()
        temp_analyte_df[analyte_data.trial_identifier.analyte_name] = analyte_data.pd_series

        # Merging the dataframes this way will allow different time indices for different analytes
        self.analyte_df = pd.merge(self.analyte_df,temp_analyte_df,left_index=True,right_index=True, how='outer')
        self.t = self.analyte_df.index


# Features
class MultiAnalyteFeature(object):
    """
    Base multi analyte feature. Use this to create new features.
    """
    def __init__(self):
        self.analyte_list = []
        self.name = ''

    @property
    def data(self):
        return 'Not implemented'

# class YieldTimePoint(object):
#     __tablename__ = 'yield_time_point'
#
#     id = Column(Integer, primary_key=True)
#     time = Column(Float)
#     data = Column(Float)



class ProductYield(MultiAnalyteFeature):
    # parent = relationship
    # yield_points = relationship('YieldTimePoint')

    def __init__(self, substrate, product):
        # self.parent = single_trial
        # self.name = 'yields_dict'
        self.requires = ['product','substrate','biomass']
        self.substrate = substrate
        self.product = product

    @property
    def data(self):
        self.calculate()
        return self.product_yield

    def calculate(self):
        self.calculate_substrate_consumed()
        try:
            self.product_yield = np.divide(
                [(dataPoint - self.product.data_vector[0]) for dataPoint in self.product.data_vector],
                self.substrate_consumed
            )
        except Exception as e:
            print(self.product)
            print(self.product.data_vector)
            raise Exception(e)

    def calculate_substrate_consumed(self):
        self.substrate_consumed = np.array(
            [(self.substrate.data_vector[0] - dataPoint)
             for dataPoint in self.substrate.data_vector]
        )


class ProductYieldFactory(object):
    def __init__(self):
        self.products = []
        self.requires = ['substrate','product', 'biomass']
        self.name = 'product_yield'
        self.substrate = None

    def add_analyte_data(self, analyte_data):
        if analyte_data.trial_identifier.analyte_type == 'substrate':
            if self.substrate is None:
                self.substrate = analyte_data

                if len(self.products) > 0:
                    for product in self.products:
                        product.product_yield = ProductYield(substrate=self.substrate, product=analyte_data)

                # Once we've processed the waiting products we can delete them
                del self.products
            else:
                raise Exception('No support for Multiple substrates: ',
                                self.substrate_name,
                                ' ',
                                analyte_data.trial_identifier.analyte_name)

        if analyte_data.trial_identifier.analyte_type in ['biomass','product']:
            if self.substrate is not None:
                analyte_data.product_yield = ProductYield(substrate=self.substrate, product=analyte_data)
            else:
                # Hold on to the product until a substrate is defined
                self.products.append(analyte_data)

class SpecificProductivityFactory(object):
    def __init__(self):
        self.requires = ['substrate','product','biomass']
        self.name = 'specific_productivity'
        self.biomass = None
        self.pending_analytes = []

    def add_analyte_data(self, analyte_data):
        if analyte_data.trial_identifier.analyte_type == 'biomass':
            self.biomass = analyte_data

            if len(self.pending_analytes) > 0:
                for analyte in self.pending_analytes:
                    analyte_data.specific_productivity = SpecificProductivity(biomass=self.biomass,
                                                                              analyte=analyte_data)

        if analyte_data.trial_identifier.analyte_type in ['substrate','productivity']:
            if self.biomass is not None:
                analyte_data.specific_productivity = SpecificProductivity(biomass=self.biomass, analyte=analyte_data)
            else:
                self.pending_analytes.append(analyte_data)

class SpecificProductivity(MultiAnalyteFeature):
    def __init__(self, biomass, analyte):
        self.biomass = biomass
        self.analyte = analyte

    @property
    def data(self):
        if not self.specific_productivity:
            self.calculate()

        return self.specific_productivity



    def calculate(self):
        """
        Calculate the specific productivity (dP/dt) given :math:`dP/dt = k_{Product} * X`
        """
        if self.biomass_name is None:
            return 'Biomass not defined'

        self.analyte.calculate()    # Need gradient calculated before accessing
        self.specific_productivity = self.analyte.gradient / self.biomass.data_vector

class NormalizedData(MultiAnalyteFeature):
    def __init__(self, numerator, denominator):
        pass

class COBRAModelFactory(MultiAnalyteFeature):
    def __init__(self):
        self.requires = ['biomass','substrate','product']

    def calculate(self):
        import cameo
        iJO = cameo.models.iJO1366

class MassBalanceFactory(MultiAnalyteFeature):
    def __init__(self):
        self.requires = ['biomass','substrate','product']



# class FeaturesToAnalyteData(Base):
#     feature = Column(String, 'feature.id')
#     time_course = Column(Integer,'time_course.id')

class FeatureManager(object):
    def __init__(self):
        self.features = []
        self.analytes_to_features = {}
        self.analyte_types = ['biomass','substrate','product']
        for analyte_type in self.analyte_types:
            self.analytes_to_features[analyte_type] = []

    def register_feature(self, feature):
        self.features.append(feature)

        analyte_types = ['biomass','substrate','product']
        for analyte_type in analyte_types:
            if analyte_type in feature.requires:
                self.analytes_to_features[analyte_type].append(feature)
        setattr(self,feature.name,feature)

    def add_analyte(self, analyte_data):
        for analyte_type in self.analyte_types:
            for feature in self.features:
                if feature in self.analyte_types[analyte_type]:
                    feature.add_analyte(analyte_data)

# class TimeCourseStage(TimeCourse):
#     def __init__(self):
#         TimeCourse().__init__()
#
# @TimeCourse.stage_indices.setter
# def

# class SingleTrialDataShell(SingleTrial):
#     """
#     Object which overwrites the SingleTrial objects setters and getters, acts as a shell of data with the
#     same structure as SingleTrial
#     """
#
#     def __init__(self):
#         SingleTrial.__init__(self)
#
#     @SingleTrial.substrate.setter
#     def substrate(self, substrate):
#         self._substrate = substrate
#
#     @SingleTrial.OD.setter
#     def OD(self, OD):
#         self._OD = OD
#
#     @SingleTrial.products.setter
#     def products(self, products):
#         self._products = products