import pandas as pd
import lightgbm

from bayes_opt import BayesianOptimization
from LightGBM_with_Simple_Features import bureau_and_balance, previous_applications, pos_cash, installments_payments, credit_card_balance, application_train_test

# 以下参考
# https://github.com/fmfn/BayesianOptimization
# https://www.kaggle.com/tilii7/olivier-lightgbm-parameters-by-bayesian-opt/code

NUM_ROWS=10000

# ベストスコアのカーネルと同じ特徴量を使います
BUREAU = bureau_and_balance(NUM_ROWS)
PREV = previous_applications(NUM_ROWS)
POS = pos_cash(NUM_ROWS)
INS = installments_payments(NUM_ROWS)
CC = credit_card_balance(NUM_ROWS)

# concat datasets
DF = application_train_test(NUM_ROWS)
DF = DF.join(BUREAU, how='left', on='SK_ID_CURR')
DF = DF.join(PREV, how='left', on='SK_ID_CURR')
DF = DF.join(POS, how='left', on='SK_ID_CURR')
DF = DF.join(INS, how='left', on='SK_ID_CURR')
DF = DF.join(CC, how='left', on='SK_ID_CURR')


# split test & train
TRAIN_DF = DF[DF['TARGET'].notnull()]
TEST_DF = DF[DF['TARGET'].isnull()]

# set
lgbm_train = lightgbm.Dataset(TRAIN_DF.drop('TARGET', axis=1),
                              TRAIN_DF['TARGET'])

def lgbm_eval(num_leaves,
              colsample_bytree,
              subsample,
              max_depth,
              reg_alpha,
              reg_lambda,
              min_split_gain,
              min_child_weight,
             ):

    params = dict()
    params["learning_rate"] = 0.02
    params["silent"] = True
    params["nthread"] = 16
    params["application"] = "binary"

    params["num_leaves"] = int(num_leaves)
    params['colsample_bytree'] = max(min(colsample_bytree, 1), 0)
    params['subsample'] = max(min(subsample, 1), 0)
    params['max_depth'] = int(max_depth)
    params['reg_alpha'] = max(reg_alpha, 0)
    params['reg_lambda'] = max(reg_lambda, 0)
    params['min_split_gain'] = min_split_gain
    params['min_child_weight'] = min_child_weight

    clf = lightgbm.cv(params=params,
                      train_set=lgbm_train,
                      metrics=["auc"],
                      folds=None,
                      num_boost_round=5,
                      early_stopping_rounds=10,
                      verbose_eval=1
                     )

    return clf['auc-mean'][-1]

def main():

    # clf for bayesian optimization
    clf_bo = BayesianOptimization(lgbm_eval, {'num_leaves': (30, 45),
                                              'colsample_bytree': (0.1, 1),
                                              'subsample': (0.1, 1),
                                              'max_depth': (5, 15),
                                              'reg_alpha': (0, 10),
                                              'reg_lambda': (0, 10),
                                              'min_split_gain': (0, 1),
                                              'min_child_weight': (30, 45),
                                            })

    clf_bo.maximize(init_points=4, n_iter=20)

    print(clf_bo['max']['max_val'])

if __name__ == '__main__':
    main()