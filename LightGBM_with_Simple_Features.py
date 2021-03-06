# Forked from excellent kernel : https://www.kaggle.com/jsaguiar/updated-0-792-lb-lightgbm-with-simple-features
# From Kaggler : https://www.kaggle.com/jsaguiar
# Just removed a few min, max features. U can see the CV is not good. Dont believe in LB.

import lightgbm as lgb
import numpy as np
import pandas as pd
import gc
import time

from contextlib import contextmanager
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import KFold, StratifiedKFold
import matplotlib.pyplot as plt
import seaborn as sns
import warnings
import os

warnings.simplefilter(action='ignore', category=FutureWarning)

@contextmanager
def timer(title):
    t0 = time.time()
    yield
    print("{} - done in {:.0f}s".format(title, time.time() - t0))

# One-hot encoding for categorical columns with get_dummies
def one_hot_encoder(df, nan_as_category = True):
    original_columns = list(df.columns)
    categorical_columns = [col for col in df.columns if df[col].dtype == 'object']
    df = pd.get_dummies(df, columns= categorical_columns, dummy_na= nan_as_category)
    new_columns = [c for c in df.columns if c not in original_columns]
    return df, new_columns

# Preprocess application_train.csv and application_test.csv
def application_train_test(num_rows = None, nan_as_category = False):
    # Read data and merge
    df = pd.read_csv('application_train.csv', nrows= num_rows)
    test_df = pd.read_csv('application_test.csv', nrows= num_rows)
    print("Train samples: {}, test samples: {}".format(len(df), len(test_df)))
    df = df.append(test_df).reset_index()
    # Optional: Remove 4 applications with XNA CODE_GENDER (train set)
    df = df[df['CODE_GENDER'] != 'XNA']

    docs = [_f for _f in df.columns if 'FLAG_DOC' in _f]
    live = [_f for _f in df.columns if ('FLAG_' in _f) & ('FLAG_DOC' not in _f) & ('_FLAG_' not in _f)]

    # NaN values for DAYS_EMPLOYED: 365.243 -> nan
    df['DAYS_EMPLOYED'].replace(365243, np.nan, inplace= True)

    # 追加の前処理 https://github.com/neptune-ml/open-solution-home-credit/wiki/LightGBM-with-smarter-features
    df['NAME_FAMILY_STATUS'].replace('Unknown', np.nan, inplace=True)
    df['DAYS_LAST_PHONE_CHANGE'].replace(0, np.nan, inplace=True)
    df['ORGANIZATION_TYPE'].replace('XNA', np.nan, inplace=True)

    inc_by_org = df[['AMT_INCOME_TOTAL', 'ORGANIZATION_TYPE']].groupby('ORGANIZATION_TYPE').median()['AMT_INCOME_TOTAL']

    df['NEW_CREDIT_TO_ANNUITY_RATIO'] = df['AMT_CREDIT'] / df['AMT_ANNUITY']
    df['NEW_CREDIT_TO_GOODS_RATIO'] = df['AMT_CREDIT'] / df['AMT_GOODS_PRICE']
    df['NEW_DOC_IND_KURT'] = df[docs].kurtosis(axis=1)
    df['NEW_LIVE_IND_SUM'] = df[live].sum(axis=1)
    df['NEW_INC_PER_CHLD'] = df['AMT_INCOME_TOTAL'] / (1 + df['CNT_CHILDREN'])
    df['NEW_INC_BY_ORG'] = df['ORGANIZATION_TYPE'].map(inc_by_org)
    df['NEW_EMPLOY_TO_BIRTH_RATIO'] = df['DAYS_EMPLOYED'] / df['DAYS_BIRTH']
    df['NEW_ANNUITY_TO_INCOME_RATIO'] = df['AMT_ANNUITY'] / (1 + df['AMT_INCOME_TOTAL'])
    df['NEW_SOURCES_PROD'] = df['EXT_SOURCE_1'] * df['EXT_SOURCE_2'] * df['EXT_SOURCE_3']
    df['NEW_EXT_SOURCES_MEAN'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3']].mean(axis=1)
    df['NEW_SCORES_STD'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3']].std(axis=1)
    df['NEW_SCORES_STD'] = df['NEW_SCORES_STD'].fillna(df['NEW_SCORES_STD'].mean())
    df['NEW_CAR_TO_BIRTH_RATIO'] = df['OWN_CAR_AGE'] / df['DAYS_BIRTH']
    df['NEW_CAR_TO_EMPLOY_RATIO'] = df['OWN_CAR_AGE'] / df['DAYS_EMPLOYED']
    df['NEW_PHONE_TO_BIRTH_RATIO'] = df['DAYS_LAST_PHONE_CHANGE'] / df['DAYS_BIRTH']
    df['NEW_PHONE_TO_BIRTH_RATIO'] = df['DAYS_LAST_PHONE_CHANGE'] / df['DAYS_EMPLOYED']
    df['NEW_CREDIT_TO_INCOME_RATIO'] = df['AMT_CREDIT'] / df['AMT_INCOME_TOTAL']

    # ここから追加したやつ
    df['NEW_EXT_SOURCE_RATIO12'] = df['EXT_SOURCE_1'] / df['EXT_SOURCE_2']
    df['NEW_EXT_SOURCE_RATIO23'] = df['EXT_SOURCE_2'] / df['EXT_SOURCE_3']
    df['NEW_EXT_SOURCE_RATIO31'] = df['EXT_SOURCE_3'] / df['EXT_SOURCE_1']
    df['NEW_INCOME_TO_BIRTH_RATIO'] = df['AMT_INCOME_TOTAL'] / df['DAYS_BIRTH']
    df['NEW_ANNUITY_TO_BIRTH_RATIO'] = df['AMT_ANNUITY'] / df['DAYS_BIRTH']
    df['NEW_CREDIT_TO_BIRTH_RATIO'] = df['AMT_CREDIT'] / df['DAYS_BIRTH']
    df['NEW_EXT_SOURCES_MEAN12'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2']].mean(axis=1)
    df['NEW_EXT_SOURCES_MEAN23'] = df[['EXT_SOURCE_2', 'EXT_SOURCE_3']].mean(axis=1)
    df['NEW_EXT_SOURCES_MEAN31'] = df[['EXT_SOURCE_3', 'EXT_SOURCE_1']].mean(axis=1)
    df['NEW_SOURCES_PROD12'] = df['EXT_SOURCE_1'] * df['EXT_SOURCE_2']
    df['NEW_SOURCES_PROD23'] = df['EXT_SOURCE_2'] * df['EXT_SOURCE_3']
    df['NEW_SOURCES_PROD31'] = df['EXT_SOURCE_3'] * df['EXT_SOURCE_1']

    # 更に追加したやつ　参考 https://github.com/neptune-ml/open-solution-home-credit/wiki/LightGBM-on-selected-features
    df['NEW_CHILDREN_RATIO'] = df['CNT_CHILDREN'] / df['CNT_FAM_MEMBERS']
    df['NEW_INCOME_PER_PERSON'] = df['AMT_INCOME_TOTAL'] / df['CNT_FAM_MEMBERS']
    df['NEW_PAYMENT_RATE'] = df['AMT_ANNUITY'] / df['AMT_CREDIT'] # これ被ってる気がしますが一応入れときます
    df['NEW_EXT_SOURCE_WEIGHTED'] = df['EXT_SOURCE_1']*2 + df['EXT_SOURCE_2'] * 3 + df['EXT_SOURCE_3'] * 4
    df['NEW_CNT_NON_CHILD'] = df['CNT_FAM_MEMBERS'] - df['CNT_CHILDREN']
    df['NEW_CHILD_TO_NON_CHILD_RATIO'] = df['CNT_CHILDREN'] / df['NEW_CNT_NON_CHILD']
    df['NEW_INCOME_PER_NON_CHILD'] = df['AMT_INCOME_TOTAL'] / df['NEW_CNT_NON_CHILD']
    df['NEW_CREDIT_PER_PERSON'] = df['AMT_CREDIT'] / df['CNT_FAM_MEMBERS']
    df['NEW_CREDIT_PER_CHILD'] = df['AMT_CREDIT'] / (1 + df['CNT_CHILDREN'])
    df['NEW_CREDIT_PER_NON_CHILD'] = df['AMT_CREDIT'] / df['NEW_CNT_NON_CHILD']
    df['NEW_YOUNG_AGE'] = (df['DAYS_BIRTH'] < -14000).astype(int)
    df['NEW_SHORT_EMPLOYMENT'] = (df['DAYS_EMPLOYED'] < -2000).astype(int)

    # EXT_SOURCE系大事っぽいので組み合わせ追加します by藤原
    df['NEW_SOURCES_MIN'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3']].min(axis=1)
    df['NEW_SOURCES_MIN12'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2']].min(axis=1)
    df['NEW_SOURCES_MIN23'] = df[['EXT_SOURCE_2', 'EXT_SOURCE_3']].min(axis=1)
    df['NEW_SOURCES_MIN31'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_3']].min(axis=1)
    df['NEW_SOURCES_MAX'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3']].max(axis=1)
    df['NEW_SOURCES_MAX12'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2']].max(axis=1)
    df['NEW_SOURCES_MAX23'] = df[['EXT_SOURCE_2', 'EXT_SOURCE_3']].max(axis=1)
    df['NEW_SOURCES_MAX31'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_3']].max(axis=1)
    df['NEW_SOURCES_SUM'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3']].sum(axis=1)
    df['NEW_SOURCES_SUM12'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2']].sum(axis=1)
    df['NEW_SOURCES_SUM23'] = df[['EXT_SOURCE_2', 'EXT_SOURCE_3']].sum(axis=1)
    df['NEW_SOURCES_SUM31'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_3']].sum(axis=1)
    df['NEW_SOURCES_MEDIAN'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3']].median(axis=1)
    df['NEW_SOURCES_MEDIAN12'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_2']].median(axis=1)
    df['NEW_SOURCES_MEDIAN23'] = df[['EXT_SOURCE_2', 'EXT_SOURCE_3']].median(axis=1)
    df['NEW_SOURCES_MEDIAN31'] = df[['EXT_SOURCE_1', 'EXT_SOURCE_3']].median(axis=1)

    # Categorical features with Binary encode (0 or 1; two categories)
    for bin_feature in ['CODE_GENDER', 'FLAG_OWN_CAR', 'FLAG_OWN_REALTY']:
        df[bin_feature], uniques = pd.factorize(df[bin_feature])
    # Categorical features with One-Hot encode
    df, cat_cols = one_hot_encoder(df, nan_as_category)
    dropcolum=['FLAG_DOCUMENT_2','FLAG_DOCUMENT_4',
    'FLAG_DOCUMENT_5','FLAG_DOCUMENT_6','FLAG_DOCUMENT_7',
    'FLAG_DOCUMENT_8','FLAG_DOCUMENT_9','FLAG_DOCUMENT_10',
    'FLAG_DOCUMENT_11','FLAG_DOCUMENT_12','FLAG_DOCUMENT_13',
    'FLAG_DOCUMENT_14','FLAG_DOCUMENT_15','FLAG_DOCUMENT_16',
    'FLAG_DOCUMENT_17','FLAG_DOCUMENT_18','FLAG_DOCUMENT_19',
    'FLAG_DOCUMENT_20','FLAG_DOCUMENT_21']
    df= df.drop(dropcolum,axis=1)

    del test_df
    gc.collect()
    return df

# Preprocess bureau.csv and bureau_balance.csv
def bureau_and_balance(num_rows = None, nan_as_category = True):
    bureau = pd.read_csv('bureau.csv', nrows = num_rows)
    bb = pd.read_csv('bureau_balance.csv', nrows = num_rows)

    # 追加の特徴量　https://github.com/neptune-ml/open-solution-home-credit/blob/master/src/feature_extraction.py
    bureau['CREDIT_ACTIVE_BINARY'] = (bureau['CREDIT_ACTIVE'] != 'Closed').astype(int)
    bureau['CREDIT_ENDDATE_BINARY'] = (bureau['DAYS_CREDIT_ENDDATE'] > 0).astype(int)

    bb, bb_cat = one_hot_encoder(bb, nan_as_category)
    bureau, bureau_cat = one_hot_encoder(bureau, nan_as_category)

    # Bureau balance: Perform aggregations and merge with bureau.csv
    bb_aggregations = {'MONTHS_BALANCE': ['min', 'max', 'size']}
    for col in bb_cat:
        bb_aggregations[col] = ['mean']
    bb_agg = bb.groupby('SK_ID_BUREAU').agg(bb_aggregations)
    bb_agg.columns = pd.Index([e[0] + "_" + e[1].upper() for e in bb_agg.columns.tolist()])
    bureau = bureau.join(bb_agg, how='left', on='SK_ID_BUREAU')
    bureau.drop(['SK_ID_BUREAU'], axis=1, inplace= True)
    del bb, bb_agg
    gc.collect()

    # 追加の前処理 https://github.com/neptune-ml/open-solution-home-credit/wiki/LightGBM-with-smarter-features
    bureau['AMT_CREDIT_SUM'].fillna(0, inplace=True)
    bureau['AMT_CREDIT_SUM_DEBT'].fillna(0, inplace=True)
    bureau['AMT_CREDIT_SUM_OVERDUE'].fillna(0, inplace=True)
    bureau['CNT_CREDIT_PROLONG'].fillna(0, inplace=True)
    bureau['DAYS_CREDIT_ENDDATE'][bureau['DAYS_CREDIT_ENDDATE'] < -40000] = np.nan
    bureau['DAYS_CREDIT_UPDATE'][bureau['DAYS_CREDIT_UPDATE'] < -40000] = np.nan
    bureau['DAYS_ENDDATE_FACT'][bureau['DAYS_ENDDATE_FACT'] < -40000] = np.nan

    # 追加します　→表記分かりやすいように変更しましたby藤原
    bureau['CREDIT_SUM_TO_DEBT_RATIO'] = bureau['AMT_CREDIT_SUM']/bureau['AMT_CREDIT_SUM_DEBT']
    bureau['CREDIT_SUM_TO_LIMIT_RATIO'] = bureau['AMT_CREDIT_SUM']/bureau['AMT_CREDIT_SUM_LIMIT']
    bureau['CREDIT_SUM_TO_OVERDUE_RATIO'] = bureau['AMT_CREDIT_SUM']/bureau['AMT_CREDIT_SUM_OVERDUE']
    bureau['CREDIT_SUM_TO_MAX_OVERDUE_RATIO'] = bureau['AMT_CREDIT_SUM']/bureau['AMT_CREDIT_MAX_OVERDUE']
    bureau['CREDIT_SUM_TO_ANNUITY_RATIO'] = bureau['AMT_CREDIT_SUM']/bureau['AMT_ANNUITY']

    # DAYS_CREDITを起点にした特徴量
    bureau['MAX_OVERDUE_TO_DAYS_CREDIT_RATIO'] = bureau['AMT_CREDIT_MAX_OVERDUE']/bureau['DAYS_CREDIT']
    bureau['DAY_OVERDUE_TO_DAYS_CREDIT_RATIO'] = bureau['CREDIT_DAY_OVERDUE']/bureau['DAYS_CREDIT']
    bureau['ENDDATE_TO_DAYS_CREDIT_RATIO'] = bureau['DAYS_CREDIT_ENDDATE']/bureau['DAYS_CREDIT']
    bureau['ENDDATE_FACT_TO_DAYS_CREDIT_RATIO'] = bureau['DAYS_ENDDATE_FACT']/bureau['DAYS_CREDIT']
    bureau['UPDATE_TO_DAYS_CREDIT_RATIO'] = bureau['DAYS_CREDIT_UPDATE']/bureau['DAYS_CREDIT']

    # Bureau and bureau_balance numeric features
    num_aggregations = {
        'DAYS_CREDIT': [ 'mean', 'var', 'max', 'min', 'skew'], # 強そうな特徴量にはskewも追加する方針です。
        'DAYS_CREDIT_ENDDATE': [ 'mean'],
        'DAYS_CREDIT_UPDATE': ['mean'],
        'CREDIT_DAY_OVERDUE': ['mean'],
        'AMT_CREDIT_MAX_OVERDUE': ['mean', 'var', 'max', 'min', 'skew'], # 強そうな特徴量にはskewも追加する方針です。
        'AMT_CREDIT_SUM': [ 'mean', 'sum'],
        'AMT_CREDIT_SUM_DEBT': [ 'mean', 'sum'],
        'AMT_CREDIT_SUM_OVERDUE': ['mean'],
        'AMT_CREDIT_SUM_LIMIT': ['mean', 'sum'],
        'AMT_ANNUITY': ['max', 'mean'],
#        'CNT_CREDIT_PROLONG': ['sum'],
        'MONTHS_BALANCE_MIN': ['min'],
        'MONTHS_BALANCE_MAX': ['max'],
        'MONTHS_BALANCE_SIZE': ['mean', 'sum'],
        'CREDIT_SUM_TO_DEBT_RATIO':['mean','max','min'],
        'CREDIT_SUM_TO_LIMIT_RATIO':['mean','max','min'],
        'CREDIT_SUM_TO_OVERDUE_RATIO':['mean','max','min'],
        'CREDIT_SUM_TO_MAX_OVERDUE_RATIO':['min'],
        'CREDIT_SUM_TO_ANNUITY_RATIO':['mean','var','max','min'],
        'MAX_OVERDUE_TO_DAYS_CREDIT_RATIO':['mean','var','max','min','skew'],
        'DAY_OVERDUE_TO_DAYS_CREDIT_RATIO':['var','skew'],
        'ENDDATE_TO_DAYS_CREDIT_RATIO':['mean','var','max','min','skew'],
        'ENDDATE_FACT_TO_DAYS_CREDIT_RATIO':['mean','var','max','min','skew'],
        'UPDATE_TO_DAYS_CREDIT_RATIO':['mean','var','max','min','skew'],
        'CREDIT_ACTIVE_BINARY':['mean'],
        'CREDIT_ENDDATE_BINARY':['mean']
    }
    # Bureau and bureau_balance categorical features
    cat_aggregations = {}
    for cat in bureau_cat: cat_aggregations[cat] = ['mean']
    for cat in bb_cat: cat_aggregations[cat + "_MEAN"] = ['mean']

    bureau_agg = bureau.groupby('SK_ID_CURR').agg({**num_aggregations, **cat_aggregations})
    bureau_agg.columns = pd.Index(['BURO_' + e[0] + "_" + e[1].upper() for e in bureau_agg.columns.tolist()])
    # Bureau: Active credits - using only numerical aggregations
    active = bureau[bureau['CREDIT_ACTIVE_Active'] == 1]
    active_agg = active.groupby('SK_ID_CURR').agg(num_aggregations)
    active_agg.columns = pd.Index(['ACTIVE_' + e[0] + "_" + e[1].upper() for e in active_agg.columns.tolist()])
    bureau_agg = bureau_agg.join(active_agg, how='left', on='SK_ID_CURR')
    del active, active_agg
    gc.collect()
    # Bureau: Closed credits - using only numerical aggregations
    closed = bureau[bureau['CREDIT_ACTIVE_Closed'] == 1]
    closed_agg = closed.groupby('SK_ID_CURR').agg(num_aggregations)
    closed_agg.columns = pd.Index(['CLOSED_' + e[0] + "_" + e[1].upper() for e in closed_agg.columns.tolist()])
    bureau_agg = bureau_agg.join(closed_agg, how='left', on='SK_ID_CURR')

    # 新たに追加した変数です
    bureau_agg['BURO_CREDIT_ACTIVE_CLOSED_RATIO']=bureau_agg['BURO_CREDIT_ACTIVE_Active_MEAN']/bureau_agg['BURO_CREDIT_ACTIVE_Closed_MEAN']

    # TODO:
    """
    features['bureau_average_of_past_loans_per_type'] = \
        features['bureau_number_of_past_loans'] / features['bureau_number_of_loan_types']

    features['bureau_debt_credit_ratio'] = \
        features['bureau_total_customer_debt'] / features['bureau_total_customer_credit']

    features['bureau_overdue_debt_ratio'] = \
        features['bureau_total_customer_overdue'] / features['bureau_total_customer_debt']
    """

    del closed, closed_agg, bureau
    gc.collect()
    return bureau_agg

# Preprocess previous_applications.csv
def previous_applications(num_rows = None, nan_as_category = True):
    prev = pd.read_csv('previous_application.csv', nrows = num_rows)
    prev, cat_cols = one_hot_encoder(prev, nan_as_category= True)
    # Days 365.243 values -> nan
    prev['DAYS_FIRST_DRAWING'].replace(365243, np.nan, inplace= True)
    prev['DAYS_FIRST_DUE'].replace(365243, np.nan, inplace= True)
    prev['DAYS_LAST_DUE_1ST_VERSION'].replace(365243, np.nan, inplace= True)
    prev['DAYS_LAST_DUE'].replace(365243, np.nan, inplace= True)
    prev['DAYS_TERMINATION'].replace(365243, np.nan, inplace= True)

    # fill nan as zero
    prev['RATE_DOWN_PAYMENT']=prev['RATE_DOWN_PAYMENT'].fillna(0)

    # Add feature: value ask / value received percentage
    prev['APP_CREDIT_PERC'] = prev['AMT_APPLICATION'] / prev['AMT_CREDIT']

    # ここから新規に追加した特徴量
    prev['CREDIT_TO_ANNUITY_RATIO'] = prev['AMT_CREDIT'] / prev['AMT_ANNUITY']
    prev['CREDIT_TO_GOODS_RATIO'] = prev['AMT_CREDIT'] / prev['AMT_GOODS_PRICE']
    prev['CREDIT_PERC_TO_ANNUITY_RATIO'] = prev['APP_CREDIT_PERC'] / prev['AMT_ANNUITY']
    prev['CREDIT_PERC_TO_GOODS_RATIO'] = prev['APP_CREDIT_PERC'] / prev['AMT_GOODS_PRICE']
    prev['ANNUITY_TO_CNT_PAYMENT_RATIO'] = prev['AMT_ANNUITY'] / prev['CNT_PAYMENT']
    prev['APPLICATION_TO_CNT_PAYMENT_RATIO'] = prev['AMT_APPLICATION'] / prev['CNT_PAYMENT']
    prev['CREDIT_TO_CNT_PAYMENT_RATIO'] = prev['AMT_CREDIT'] / prev['CNT_PAYMENT']
    prev['DOWN_PAYMENT_TO_CNT_PAYMENT_RATIO'] = prev['AMT_DOWN_PAYMENT'] / prev['CNT_PAYMENT']
    prev['GOODS_PRICE_TO_CNT_PAYMENT_RATIO'] = prev['AMT_GOODS_PRICE'] / prev['CNT_PAYMENT']
    prev['ANNUITY_TO_DAYS_DECISION_RATIO'] = prev['AMT_ANNUITY'] / prev['DAYS_DECISION']
    prev['CREDIT_TO_DAYS_DECISION_RATIO'] = prev['AMT_CREDIT'] / prev['DAYS_DECISION']
    prev['CREDIT_PERC_TO_DAYS_DECISION_RATIO'] = prev['APP_CREDIT_PERC'] / prev['DAYS_DECISION']
    prev['GOODS_TO_DAYS_DECISION_RATIO'] = prev['AMT_GOODS_PRICE'] / prev['DAYS_DECISION']

    # Previous applications numeric features
    num_aggregations = {
        'AMT_ANNUITY': [ 'max', 'mean'],
        'AMT_APPLICATION': [ 'max','mean'],
        'AMT_CREDIT': [ 'max', 'mean'],
        'APP_CREDIT_PERC': [ 'max', 'mean'],
        'AMT_DOWN_PAYMENT': [ 'max', 'mean'],
        'AMT_GOODS_PRICE': [ 'max', 'mean'],
        'HOUR_APPR_PROCESS_START': [ 'max', 'mean'],
        'RATE_DOWN_PAYMENT': [ 'max', 'mean'],
        'DAYS_DECISION': [ 'max', 'mean'],
        'CNT_PAYMENT': ['mean','sum','var','max','min','skew'],
        'CREDIT_TO_ANNUITY_RATIO':['mean','var','max','min','skew'],
        'CREDIT_TO_GOODS_RATIO':['mean','var','max','min','skew'],
        'CREDIT_PERC_TO_ANNUITY_RATIO':['mean','var','max','min','skew'],
        'CREDIT_PERC_TO_GOODS_RATIO':['mean','var','max','min','skew'],
        'ANNUITY_TO_CNT_PAYMENT_RATIO':['mean','var','max','min','skew'],
        'APPLICATION_TO_CNT_PAYMENT_RATIO':['mean','var','max','min','skew'],
        'CREDIT_TO_CNT_PAYMENT_RATIO':['mean','var','max','min','skew'],
        'DOWN_PAYMENT_TO_CNT_PAYMENT_RATIO':['mean','var','max','min','skew'],
        'GOODS_PRICE_TO_CNT_PAYMENT_RATIO':['mean','var','max','min','skew'],
        'ANNUITY_TO_DAYS_DECISION_RATIO':['mean','var','max','min','skew'],
        'CREDIT_TO_DAYS_DECISION_RATIO':['mean','var','max','min','skew'],
        'CREDIT_PERC_TO_DAYS_DECISION_RATIO':['mean','var','max','min','skew'],
        'GOODS_TO_DAYS_DECISION_RATIO':['mean','var','max','min','skew']
    }
    # Previous applications categorical features
    cat_aggregations = {}
    for cat in cat_cols:
        cat_aggregations[cat] = ['mean']

    prev_agg = prev.groupby('SK_ID_CURR').agg({**num_aggregations, **cat_aggregations})
    prev_agg.columns = pd.Index(['PREV_' + e[0] + "_" + e[1].upper() for e in prev_agg.columns.tolist()])
    # Previous Applications: Approved Applications - only numerical features
    approved = prev[prev['NAME_CONTRACT_STATUS_Approved'] == 1]
    approved_agg = approved.groupby('SK_ID_CURR').agg(num_aggregations)
    approved_agg.columns = pd.Index(['APPROVED_' + e[0] + "_" + e[1].upper() for e in approved_agg.columns.tolist()])
    prev_agg = prev_agg.join(approved_agg, how='left', on='SK_ID_CURR')
    # Previous Applications: Refused Applications - only numerical features
    refused = prev[prev['NAME_CONTRACT_STATUS_Refused'] == 1]
    refused_agg = refused.groupby('SK_ID_CURR').agg(num_aggregations)
    refused_agg.columns = pd.Index(['REFUSED_' + e[0] + "_" + e[1].upper() for e in refused_agg.columns.tolist()])
    prev_agg = prev_agg.join(refused_agg, how='left', on='SK_ID_CURR')

    del refused, refused_agg, approved, approved_agg, prev
    gc.collect()
    return prev_agg

# Preprocess POS_CASH_balance.csv
def pos_cash(num_rows = None, nan_as_category = True):
    pos = pd.read_csv('POS_CASH_balance.csv', nrows = num_rows)

    # 追加の特徴量 https://github.com/neptune-ml/open-solution-home-credit/blob/master/src/feature_extraction.py
    pos['IS_CONTRACT_STATUS_COMPLETED'] = (pos['NAME_CONTRACT_STATUS'] == 'Completed').astype(int)
    pos['POS_CASH_PAID_LATE'] = (pos['SK_DPD'] > 0).astype(int)
    pos['POS_CASH_PAID_LATE_WITH_TOLERANCE'] = (pos['SK_DPD_DEF'] > 0).astype(int)

    pos, cat_cols = one_hot_encoder(pos, nan_as_category= True)

    # added_feature
    pos['MONTHS_BALANCE_INSTALLMENT_FUTURE_RATIO'] = pos['MONTHS_BALANCE']*(-1.0)/pos['CNT_INSTALMENT_FUTURE']
    pos['MONTHS_BALANCE_INSTALLMENT_RATIO'] = pos['MONTHS_BALANCE']*(-1.0)/pos['CNT_INSTALMENT']
    pos['INSTALMENT_FUTURE_RATIO'] = pos['CNT_INSTALMENT_FUTURE']*1.0/pos['CNT_INSTALMENT']

    # Features
    aggregations = {
        'MONTHS_BALANCE': ['max', 'mean', 'size'],
        'SK_DPD': ['max', 'mean'],
        'SK_DPD_DEF': ['max', 'mean'],
        'MONTHS_BALANCE_INSTALLMENT_FUTURE_RATIO':['mean','max','min','var','skew'],
        'MONTHS_BALANCE_INSTALLMENT_RATIO':['mean','max','min','var','skew'],
        'INSTALMENT_FUTURE_RATIO':['mean','min','var','skew'],
        'IS_CONTRACT_STATUS_COMPLETED':['mean'],
        'POS_CASH_PAID_LATE':['mean'],
        'POS_CASH_PAID_LATE_WITH_TOLERANCE':['mean']
    }
    for cat in cat_cols:
        aggregations[cat] = ['mean']

    pos_agg = pos.groupby('SK_ID_CURR').agg(aggregations)
    pos_agg.columns = pd.Index(['POS_' + e[0] + "_" + e[1].upper() for e in pos_agg.columns.tolist()])
    # Count pos cash accounts
    pos_agg['POS_COUNT'] = pos.groupby('SK_ID_CURR').size()
    del pos
    gc.collect()
    return pos_agg

# Preprocess installments_payments.csv
def installments_payments(num_rows = None, nan_as_category = True):
    ins = pd.read_csv('installments_payments.csv', nrows = num_rows)
    ins, cat_cols = one_hot_encoder(ins, nan_as_category= True)
    # Percentage and difference paid in each installment (amount paid and installment value)
    ins['PAYMENT_PERC'] = ins['AMT_PAYMENT'] / ins['AMT_INSTALMENT']
    ins['PAYMENT_DIFF'] = ins['AMT_INSTALMENT'] - ins['AMT_PAYMENT']
    # Days past due and days before due (no negative values)
    ins['DPD'] = ins['DAYS_ENTRY_PAYMENT'] - ins['DAYS_INSTALMENT']
    ins['DBD'] = ins['DAYS_INSTALMENT'] - ins['DAYS_ENTRY_PAYMENT']
    ins['DPD'] = ins['DPD'].apply(lambda x: x if x > 0 else 0)
    ins['DBD'] = ins['DBD'].apply(lambda x: x if x > 0 else 0)
    # 追加しました
    ins['instalment_dummy'] = ins['NUM_INSTALMENT_VERSION'].map(lambda x:1 if x==0 else 0)
    ins['DAYS_PERC'] = ins['DAYS_ENTRY_PAYMENT']*1.0 / ins['DAYS_INSTALMENT']
    # Features: Perform aggregations
    aggregations = {
        'NUM_INSTALMENT_VERSION': ['nunique'],
        'DPD': ['max', 'mean', 'sum'],
        'DBD': ['max', 'mean', 'sum'],
        'PAYMENT_PERC': [ 'mean',  'var'],
        'PAYMENT_DIFF': [ 'mean', 'var'],
        'DAYS_PERC': [ 'mean', 'var'],
        'AMT_INSTALMENT': ['max', 'mean', 'sum'],
        'AMT_PAYMENT': ['min', 'max', 'mean', 'sum'],
        'DAYS_ENTRY_PAYMENT': ['max', 'mean', 'sum']
    }
    for cat in cat_cols:
        aggregations[cat] = ['mean']
    ins_agg = ins.groupby('SK_ID_CURR').agg(aggregations)
    ins_agg.columns = pd.Index(['INSTAL_' + e[0] + "_" + e[1].upper() for e in ins_agg.columns.tolist()])
    # Count installments accounts
    ins_agg['INSTAL_COUNT'] = ins.groupby('SK_ID_CURR').size()
    del ins
    gc.collect()
    return ins_agg

# Preprocess credit_card_balance.csv
def credit_card_balance(num_rows = None, nan_as_category = True):
    cc = pd.read_csv('credit_card_balance.csv', nrows = num_rows)
    cc, cat_cols = one_hot_encoder(cc, nan_as_category= True)
    # General aggregations
    cc.drop(['SK_ID_PREV'], axis= 1, inplace = True)

    # 追加の前処理 https://github.com/neptune-ml/open-solution-home-credit/wiki/LightGBM-with-smarter-features
    cc['AMT_DRAWINGS_ATM_CURRENT'][cc['AMT_DRAWINGS_ATM_CURRENT'] < 0] = np.nan
    cc['AMT_DRAWINGS_CURRENT'][cc['AMT_DRAWINGS_CURRENT'] < 0] = np.nan

    # 特徴量追加するやでー
    cc['AMT_PAYMENT_CURRENT_TOTAL_RATIO'] = cc['AMT_PAYMENT_CURRENT']*1.0/cc['AMT_PAYMENT_TOTAL_CURRENT']
    cc['CNT_DRAWINGS_ATM_CURRENT_RATIO'] = cc['CNT_DRAWINGS_ATM_CURRENT']*1.0/cc['CNT_DRAWINGS_CURRENT']
    cc['AMT_INST_MIN_REGULARITY_CURRENT_RATIO'] = cc['AMT_INST_MIN_REGULARITY']*1.0/cc['AMT_PAYMENT_CURRENT']
    cc['AMT_INST_MIN_REGULARITY_TOTAL_CURRENT_RATIO'] = cc['AMT_INST_MIN_REGULARITY']*1.0/cc['AMT_PAYMENT_TOTAL_CURRENT']

    # 追加の特徴量 https://github.com/neptune-ml/open-solution-home-credit/blob/master/src/feature_extraction.py
    cc['BALANCE_TO_LIMIT_RATIO'] = cc['AMT_BALANCE'] / cc['AMT_CREDIT_LIMIT_ACTUAL']

    # 処理も追加じゃー
    aggregations = {
        'MONTHS_BALANCE':[ 'max', 'mean', 'sum', 'var'],
        'AMT_BALANCE':[ 'max', 'mean', 'sum', 'var'],
        'AMT_CREDIT_LIMIT_ACTUAL':[ 'max', 'mean', 'sum', 'var'],
        'AMT_DRAWINGS_ATM_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'AMT_DRAWINGS_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'AMT_DRAWINGS_OTHER_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'AMT_DRAWINGS_POS_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'AMT_INST_MIN_REGULARITY':[ 'max', 'mean', 'sum', 'var'],
        'AMT_PAYMENT_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'AMT_PAYMENT_TOTAL_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'AMT_RECEIVABLE_PRINCIPAL':[ 'max', 'mean', 'sum', 'var'],
        'AMT_RECIVABLE':[ 'max', 'mean', 'sum', 'var'],
        'AMT_TOTAL_RECEIVABLE':[ 'max', 'mean', 'sum', 'var'],
        'CNT_DRAWINGS_ATM_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'CNT_DRAWINGS_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'CNT_DRAWINGS_OTHER_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'CNT_DRAWINGS_POS_CURRENT':[ 'max', 'mean', 'sum', 'var'],
        'CNT_INSTALMENT_MATURE_CUM':[ 'max', 'mean', 'sum', 'var'],
        'SK_DPD':[ 'max', 'mean', 'sum', 'var'],
        'SK_DPD_DEF':[ 'max', 'mean', 'sum', 'var'],
        'AMT_PAYMENT_CURRENT_TOTAL_RATIO': ['mean','var'],
        'CNT_DRAWINGS_ATM_CURRENT_RATIO': [ 'max', 'mean', 'sum', 'var'],
        'AMT_INST_MIN_REGULARITY_CURRENT_RATIO': [ 'max', 'mean', 'sum', 'var'],
        'AMT_INST_MIN_REGULARITY_TOTAL_CURRENT_RATIO': [ 'max', 'mean', 'sum', 'var'],
        'BALANCE_TO_LIMIT_RATIO': [ 'max', 'mean', 'sum', 'var']
    }
    for cat in cat_cols:
        aggregations[cat] = ['mean']

    #cc_agg = cc.groupby('SK_ID_CURR').agg([ 'max', 'mean', 'sum', 'var'])
    cc_agg = cc.groupby('SK_ID_CURR').agg(aggregations)
    cc_agg.columns = pd.Index(['CC_' + e[0] + "_" + e[1].upper() for e in cc_agg.columns.tolist()])
    # Count credit card lines
    cc_agg['CC_COUNT'] = cc.groupby('SK_ID_CURR').size()
    # TODO:
    """
    features['credit_card_cash_card_ratio'] = features['credit_card_drawings_atm'] / features[
        'credit_card_drawings_total']

    features['credit_card_installments_per_loan'] = (
        features['credit_card_total_installments'] / features['credit_card_number_of_loans'])
    """
    del cc
    gc.collect()
    return cc_agg

# LightGBM GBDT with KFold or Stratified KFold
# Parameters from Tilii kernel: https://www.kaggle.com/tilii7/olivier-lightgbm-parameters-by-bayesian-opt/code
def kfold_lightgbm(df, num_folds, stratified = False, debug= False):

    # Divide in training/validation and test data
    train_df = df[df['TARGET'].notnull()]
    test_df = df[df['TARGET'].isnull()]

    print("Starting LightGBM. Train shape: {}, test shape: {}".format(train_df.shape, test_df.shape))
    del df
    gc.collect()

    # Cross validation model
    if stratified:
        folds = StratifiedKFold(n_splits= num_folds, shuffle=True, random_state=47)
    else:
        folds = KFold(n_splits= num_folds, shuffle=True, random_state=47)

    # Create arrays and dataframes to store results
    oof_preds = np.zeros(train_df.shape[0])
    sub_preds = np.zeros(test_df.shape[0])
    feature_importance_df = pd.DataFrame()
    feats = [f for f in train_df.columns if f not in ['TARGET','SK_ID_CURR','SK_ID_BUREAU','SK_ID_PREV','index']]

    # 最初にsplitしないバージョンでモデルを推定します
    for n_fold, (train_idx, valid_idx) in enumerate(folds.split(train_df[feats], train_df['TARGET'])):
        train_x, train_y = train_df[feats].iloc[train_idx], train_df['TARGET'].iloc[train_idx]
        valid_x, valid_y = train_df[feats].iloc[valid_idx], train_df['TARGET'].iloc[valid_idx]

        # set data structure
        lgb_train = lgb.Dataset(train_x,
                                label=train_y,
                                free_raw_data=False)
        lgb_test = lgb.Dataset(valid_x,
                               label=valid_y,
                               free_raw_data=False)

        # LightGBM parameters found by Bayesian optimization
        params = {
                'device' : 'gpu',
#                'gpu_use_dp':True, #これで倍精度演算できるっぽいです
                'task': 'train',
#                'boosting_type': 'dart',
                'objective': 'binary',
                'metric': {'auc'},
                'num_threads': -1,
                'learning_rate': 0.02,
                'num_iteration': 10000,
                'num_leaves': 39,
                'colsample_bytree': 0.0587705926,
                'subsample': 0.5336340435,
                'max_depth': 7,
                'reg_alpha': 8.9675927624,
                'reg_lambda': 9.8953903428,
                'min_split_gain': 0.911786867,
                'min_child_weight': 37,
                'min_data_in_leaf': 629,
                'verbose': -1,
                'seed':int(2**n_fold),
                'bagging_seed':int(2**n_fold),
                'drop_seed':int(2**n_fold)
                }

        clf = lgb.train(
                        params,
                        lgb_train,
                        valid_sets=[lgb_train, lgb_test],
                        valid_names=['train', 'test'],
                        early_stopping_rounds= 200,
                        verbose_eval=100
                        )

        oof_preds[valid_idx] = clf.predict(valid_x, num_iteration=clf.best_iteration)
        sub_preds += clf.predict(test_df[feats], num_iteration=clf.best_iteration) / folds.n_splits

        fold_importance_df = pd.DataFrame()
        fold_importance_df["feature"] = feats
        fold_importance_df["importance"] = clf.feature_importance(importance_type='gain', iteration=clf.best_iteration)
        fold_importance_df["fold"] = n_fold + 1
        feature_importance_df = pd.concat([feature_importance_df, fold_importance_df], axis=0)
        print('Fold %2d AUC : %.6f' % (n_fold + 1, roc_auc_score(valid_y, oof_preds[valid_idx])))
        del clf, train_x, train_y, valid_x, valid_y
        gc.collect()

    print('Full AUC score %.6f' % roc_auc_score(train_df['TARGET'], oof_preds))

    if not debug:
        # AUDスコアを上げるため提出ファイルの調整を追加→これは最終段階で使いましょう
        # 0or1に調整する水準を決定（とりあえず上位下位0.05%以下のものを調整）→下位は10%に変更
        """
        q_high = test_df['TARGET'].quantile(0.9995)
        q_low = test_df['TARGET'].quantile(0.1)

        test_df['TARGET'] = test_df['TARGET'].apply(lambda x: 1 if x > q_high else x)
        test_df['TARGET'] = test_df['TARGET'].apply(lambda x: 0 if x < q_low else x)
        """
        # 分離前モデルの予測値を保存
        test_df['TARGET'] = sub_preds
        test_df[['SK_ID_CURR', 'TARGET']].to_csv(submission_file_name, index= False)

    return feature_importance_df

# Display/plot feature importance
def display_importances(feature_importance_df_, outputpath, csv_outputpath):
    cols = feature_importance_df_[["feature", "importance"]].groupby("feature").mean().sort_values(by="importance", ascending=False)[:40].index
    best_features = feature_importance_df_.loc[feature_importance_df_.feature.isin(cols)]

    # importance下位の確認用に追加しました
    _feature_importance_df_=feature_importance_df_.groupby('feature').sum()
    _feature_importance_df_.to_csv(csv_outputpath)

    plt.figure(figsize=(8, 10))
    sns.barplot(x="importance", y="feature", data=best_features.sort_values(by="importance", ascending=False))
    plt.title('LightGBM Features (avg over folds)')
    plt.tight_layout()
    plt.savefig(outputpath)

def main(debug = False, use_csv=False):
    num_rows = 10000 if debug else None
    if use_csv:
        # TODO # appデータだけうまく読み込めませんでした
#        df = pd.read_csv('APP.csv', index_col=0)
        df = application_train_test(num_rows)
    else:
        df = application_train_test(num_rows)
        df.to_csv('APP.csv', index=False)
    with timer("Process bureau and bureau_balance"):
        if use_csv:
            if os.environ['USER'] == 'daiyamita':
                pass
            else:
                bureau = pd.read_csv('BUREAU.csv', index_col='SK_ID_CURR')
        else:
            bureau = bureau_and_balance(num_rows)
            if os.environ['USER'] == 'daiyamita':
                pass
            else:
                bureau.to_csv('BUREAU.csv')
        print("Bureau df shape:", bureau.shape)
        df = df.join(bureau, how='left', on='SK_ID_CURR')
        del bureau
        gc.collect()
    with timer("Process previous_applications"):
        if use_csv:
            prev = pd.read_csv('PREV.csv', index_col='SK_ID_CURR')
        else:
            prev = previous_applications(num_rows)
            prev.to_csv('PREV.csv')
        print("Previous applications df shape:", prev.shape)
        df = df.join(prev, how='left', on='SK_ID_CURR')
        del prev
        gc.collect()
    with timer("Process POS-CASH balance"):
        if use_csv:
            pos = pd.read_csv('POS.csv', index_col='SK_ID_CURR')
        else:
            pos = pos_cash(num_rows)
            pos.to_csv('POS.csv')
        print("Pos-cash balance df shape:", pos.shape)
        df = df.join(pos, how='left', on='SK_ID_CURR')
        del pos
        gc.collect()
    with timer("Process installments payments"):
        if use_csv:
            ins = pd.read_csv('INS.csv', index_col='SK_ID_CURR')
        else:
            ins = installments_payments(num_rows)
            ins.to_csv('INS.csv')
        print("Installments payments df shape:", ins.shape)
        df = df.join(ins, how='left', on='SK_ID_CURR')
        del ins
        gc.collect()
    with timer("Process credit card balance"):
        if use_csv:
            cc = pd.read_csv('CC.csv', index_col='SK_ID_CURR')
        else:
            cc = credit_card_balance(num_rows)
            cc.to_csv('CC.csv')
        print("Credit card balance df shape:", cc.shape)
        df = df.join(cc, how='left', on='SK_ID_CURR')
        del cc
        gc.collect()
    with timer("Run LightGBM with kfold"):
        # 不要なカラムを落とす処理を追加
        """
        dropcolumns=pd.read_csv('feature_importance_not_to_use.csv')
        dropcolumns = dropcolumns['feature'].tolist()
        dropcolumns = [d for d in dropcolumns if d in df.columns.tolist()]

        df = df.drop(dropcolumns, axis=1)
        """

        feat_importance = kfold_lightgbm(df, num_folds= 10, stratified=True, debug= debug)

        display_importances(feat_importance ,'lgbm_importances.png', 'feature_importance.csv')

if __name__ == "__main__":
    submission_file_name = "submission_add_feature.csv"
    with timer("Full model run"):
        if os.environ['USER'] == 'daiyamita':
            main(debug = True ,use_csv=False)
        else:
            main(debug = False, use_csv=True)
