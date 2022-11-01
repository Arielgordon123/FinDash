from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from db import Record
from utils import SETTINGS, create_uuid

"""
The purpose of this module is to provide a database for transactions.
The database in a collection of parquet files, one per month, organized by year.
This is the recorded history of the transactions.
"""


@dataclass
class TransactionsDBSchema:
    ID: str = 'id'
    DATE:  datetime = 'date'
    PAYEE: str = 'payee'
    CAT: pd.CategoricalDtype = 'cat'
    MEMO: str = 'memo'
    ACCOUNT: pd.CategoricalDtype = 'account'
    INFLOW: float = 'inflow'  # if forex trans will show the conversion to ils here
    OUTFLOW: float = 'outflow'  # if forex trans will show the conversion to ils here
    RECONCILED: bool = 'reconciled'
    AMOUNT: float = 'amount'  # can be in forex

    @classmethod
    def get_mandatory_cols(cls) -> tuple:
        """
        mandatory cols every raw transactions file must have
        """
        return cls.DATE, cls.PAYEE, cls.AMOUNT

    @classmethod
    def get_non_mandatory_cols(cls) -> Dict[str, Any]:
        """
        dictionary of non-mandatory cols (keys) to add to trans file to align with
        DB schema along with default values (values)
        """
        return {cls.CAT:        '',
                cls.MEMO:       '',
                cls.ACCOUNT:    None,
                cls.INFLOW:     0,
                cls.OUTFLOW:    0,
                cls.RECONCILED: False}

    @classmethod
    def get_db_col_names(cls):
        return [f.name for f in fields(cls)]

    @classmethod
    def get_db_col_vals(cls):
        return [f.default for f in fields(cls)]

    @classmethod
    def get_db_col_dict(cls):
        return dict(zip(cls.get_db_col_names(), cls.get_db_col_vals()))

    @classmethod
    def get_numeric_cols(cls):
        return [cls.INFLOW, cls.OUTFLOW, cls.AMOUNT]


class TransactionsDBParquet:
    def __init__(self):
        self._db = self.connect(SETTINGS['db']['trans_db_path'])

    @staticmethod
    def connect(db_path: str):
        """
        load parquet files of transactions
        :param db_path: path to db root folder
        :return:
        """
        root_path = Path(db_path)

        pq_files = []
        for folder in root_path.glob('*'):
            for file in folder.iterdir():
                pq_files.append(pd.read_parquet(file))

        if len(pq_files) == 0:
            return pd.DataFrame()
        return pd.concat(pq_files)

    def disconnect(self):
        """
        In the case of a parquet db, disconnecting will only save the db
        """
        raise NotImplementedError('disconnecting from a parquet db is not implemented')

    def save_db(self, months_to_save: List[Tuple[str, str]]) -> None:
        """
        save the db to a parquet file. Saves only modified months
        :param months_to_save: list of tuples of form (year, month)
        :return:
        """
        for year, month in months_to_save:
            cond1 = self._db[TransactionsDBSchema.DATE].dt.year == int(year)
            cond2 = self._db[TransactionsDBSchema.DATE].dt.month == int(month)
            self._db[cond1 & cond2].to_parquet(Path(SETTINGS['db']['trans_db_path']) / str(year) / f'{month}.pq')

    def save_db_from_uuid(self, uuid_list: List[str]) -> None:
        """
        given a list of uuids, extracts the transaction months and saves the relevant parquet
        files
        :param uuid_list:
        :return:
        """
        months = self._get_months_from_uuid(uuid_list)
        self.save_db(months)

    def get_data_by_id(self, uuid_list: List[str]) -> pd.DataFrame:
        """
        get transactions by id
        :param uuid_list: list of uuids
        :return: dataframe of transactions
        """
        return self._db[self._db['id'].isin(uuid_list)]

    def get_data_by_col_val(self, col_val_dict: Dict[str, Any]) -> pd.DataFrame:
        """
        get transactions by column value - supports only intersection of values.
        :param col_val_dict: dict where the keys are the columns and the values are the values
                             in the columns. Supports only one value per column
        :return: dataframe of transactions
        """
        db_tmp = self._db
        for col, val in col_val_dict.items():
            db_tmp = db_tmp[db_tmp[col] == val]

        return db_tmp

    def insert_data(self, df: pd.DataFrame) -> None:
        """
        insert transactions to the db
        :param df: dataframe of transactions
        :return:
        """
        df = self._add_uuids(df)
        df = self._apply_dtypes(df)
        self._db = pd.concat([self._db, df])
        self.save_db_from_uuid(df['id'].to_list())

    def insert_record(self, record: Record):
        """
        insert a record to the db
        :param record: record to insert
        :return:
        """
        self._db = pd.concat([self._db, record.to_df()])
        self.save_db_from_uuid([record.id])

    def update_data(self):
        pass

    def delete_data(self, uuid_list: List[str]) -> None:
        """
        delete transactions from the db
        :param uuid_list: list of uuids
        :return:
        """
        months = self._get_months_from_uuid(uuid_list)
        self._db = self._db[~self._db['id'].isin(uuid_list)]
        self.save_db(months)

    def _get_months_from_uuid(self, uuid_lst: List[str]) -> List[Tuple[str, str]]:
        """
        get the months of the transactions with the given uuids
        :return: a set of lists of form [year, month]
        """
        months = set()
        for uuid in uuid_lst:
            date = self._db[self._db['id'] == uuid][TransactionsDBSchema.DATE].iloc[0]
            months.add((date.year, date.month))

        return list(months)

    @staticmethod
    def _add_uuids(df: pd.DataFrame) -> pd.DataFrame:
        """
        add uuids to the transactions
        :param df: dataframe of transactions
        :return: dataframe of transactions with uuids
        """
        # TODO: maybe vectorize the uuid creation
        df[TransactionsDBSchema.ID] = df.apply(lambda x: create_uuid(), axis=1)

        return df

    @staticmethod
    def _apply_dtypes(df):
        """
        apply the dtypes of the db schema to the dataframe
        :param df: dataframe to apply dtypes to
        :return: dataframe with dtypes applied
        """
        df[TransactionsDBSchema.DATE] = pd.to_datetime(df[TransactionsDBSchema.DATE])
        df[TransactionsDBSchema.RECONCILED] = df[TransactionsDBSchema.RECONCILED].astype(bool)
        df[TransactionsDBSchema.INFLOW] = df[TransactionsDBSchema.INFLOW].astype(float)
        df[TransactionsDBSchema.OUTFLOW] = df[TransactionsDBSchema.OUTFLOW].astype(float)
        df[TransactionsDBSchema.AMOUNT] = df[TransactionsDBSchema.AMOUNT].astype(float)
        df[TransactionsDBSchema.CAT] = df[TransactionsDBSchema.CAT].astype('category')
        df[TransactionsDBSchema.ACCOUNT] = df[TransactionsDBSchema.ACCOUNT].astype('category')
        df[TransactionsDBSchema.RECONCILED] = df[TransactionsDBSchema.RECONCILED].astype(bool)

        return df
