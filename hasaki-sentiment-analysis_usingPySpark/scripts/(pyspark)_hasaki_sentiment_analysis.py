# -*- coding: utf-8 -*-
"""(Pyspark) Hasaki sentiment analysis.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1k2eN-NCwoeff7rdP0rnl6oleW1MI70Nn
"""

# !apt update
# !apt-get install openjdk-11-jdk-headless -qq > /dev/null
# !wget -q http://archive.apache.org/dist/spark/spark-3.3.0/spark-3.3.0-bin-hadoop3.tgz
# !tar -xvf spark-3.3.0-bin-hadoop3.tgz
# !pip install -q findspark
# import os
# os.environ["JAVA_HOME"] = "/usr/lib/jvm/java-11-openjdk-amd64"
# os.environ["SPARK_HOME"] = "/content/spark-3.3.0-bin-hadoop3"

import findspark
findspark.init()

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# from google.colab import drive
# drive.mount('/content/gdrive', force_remount=True)

# %cd '/content/gdrive/My Drive/LDS9/Practice/Chapter11/'

from pyspark.sql import SparkSession

spark = SparkSession.builder \
        .appName("Hasaki Sentiment Analysis") \
        .config("spark.driver.memory", "16g") \
        .getOrCreate()

"""### Read the Data"""

data = spark.read.csv("data/Danh_gia.csv", inferSchema=True, header=True)

data.show(5)

data.printSchema()

from pyspark.sql.functions import *

data = data.withColumn('sentiment', when(data.so_sao >=4, "positive")
                               .when(data.so_sao <= 2, "negative")
                               .otherwise("neutral"))

data = data.select("noi_dung_binh_luan", "so_sao", "sentiment")

data.groupBy("sentiment").count().show()

"""### Clean and Prepare the Data
- ** Create a new length feature: **
"""

# Đếm số lượt bình luận sản phẩm
print("Num rows of training dataset: ", data.count())

# check data NULL
data.select([count(when(col(c).isNull(), c)).alias(c)
           for c in data.columns]).toPandas().T

data = data.dropna()
print("Num rows of training dataset after drop Null: ", data.count())

# Sau khi drop giá trị NULL
data.groupBy("sentiment").count().show()

from pyspark.sql.functions import length

data = data.withColumn('length',length(data['noi_dung_binh_luan']))
data.show(10)

data.groupby('sentiment').mean().show()
# Không có sự chênh lệch quá lớn về số lượng từ của các đánh giá

data = data.drop("length")

# !pip install pyspark underthesea pyvi

"""### Feature Transformations"""

from pyspark.ml.feature import Tokenizer, StopWordsRemover, RegexTokenizer
from pyspark.ml.feature import CountVectorizer, IDF, StringIndexer
from underthesea import word_tokenize

data = data.withColumn("lower_noi_dung_binh_luan", lower(data["noi_dung_binh_luan"]))

# Tokenization Vietnamese text with underthesea
def tokenize_vietnamese(text):
    return word_tokenize(text, format="text").split()

tokenizer_udf = udf(tokenize_vietnamese, ArrayType(StringType()))

data = data.withColumn("token_text", tokenizer_udf(col("lower_noi_dung_binh_luan")))
data.show()

# Vietnamese stopwords
sc = spark.sparkContext

stopwords_path = "files/vietnamese-stopwords.txt"
stopwords_rdd = sc.textFile(stopwords_path)

# Chuyển đổi sang list
vn_stopwords_rdd = stopwords_rdd.map(lambda word: word.strip()).filter(lambda word: word)
vietnamese_stopwords = stopwords_rdd.collect()
# print(vietnamese_stopwords)

vietnamese_stopwords_remover = StopWordsRemover(inputCol="token_text", outputCol="stop_tokens")
vietnamese_stopwords_remover.setStopWords(vietnamese_stopwords) #1

count_vec = CountVectorizer(inputCol='stop_tokens',outputCol='c_vec')  #2

idf = IDF(inputCol="c_vec", outputCol="tf_idf")  #3

from pyspark.ml.feature import VectorAssembler
from pyspark.ml.linalg import Vector

clean_up = VectorAssembler(inputCols=['tf_idf'],outputCol='features') #4

class_to_num = StringIndexer(inputCol='sentiment',outputCol='label') #5

"""### Pipeline"""

from pyspark.ml import Pipeline

data_prep_pipe = Pipeline(stages=[vietnamese_stopwords_remover,
                                  count_vec, idf, clean_up, class_to_num])

cleaner = data_prep_pipe.fit(data)

clean_data = cleaner.transform(data)

clean_data.show(20)

# 0:positive, 1:negative, 2:neutral
clean_data.groupBy("label").count().show()

clean_data = clean_data.select(['label','features'])

(training,testing) = clean_data.randomSplit([0.7,0.3])

training.groupBy("label").count().show()

testing.groupBy("label").count().show()

"""### Modeling

###
- Logistic Regression
"""

import time
from pyspark.ml.evaluation import MulticlassClassificationEvaluator
from pyspark.ml.classification import LogisticRegression

lg = LogisticRegression(maxIter=20, regParam=0.3, elasticNetParam=0)

# Measure training time
start_time = time.time()
predictor_lg = lg.fit(training)
end_time = time.time()

# Calculate training time
training_time_log = end_time - start_time

# Print training time
print(f"Training time: {training_time_log:.2f} seconds")

test_results_lg = predictor_lg.transform(testing)

test_results_lg.groupBy('prediction').count().show()

# Create a confusion matrix
test_results_lg.groupBy('label', 'prediction').count().show()

acc_eval = MulticlassClassificationEvaluator()
acc_lg = acc_eval.evaluate(test_results_lg)
print("Accuracy of model at predicting Logistic Regression: {}".format(acc_lg))

print("Before resampling data")
# Multiclass evaluator for precision, recall, F1-score, and accuracy
multi_evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction")

accuracy = multi_evaluator.evaluate(test_results_lg, {multi_evaluator.metricName: "accuracy"})
precision = multi_evaluator.evaluate(test_results_lg, {multi_evaluator.metricName: "weightedPrecision"})
recall = multi_evaluator.evaluate(test_results_lg, {multi_evaluator.metricName: "weightedRecall"})
f1_score = multi_evaluator.evaluate(test_results_lg, {multi_evaluator.metricName: "f1"})

# Display metrics
print(f"LR predicting Accuracy: {accuracy:.2f}")
print(f"LR predicting Precision: {precision:.2f}")
print(f"LR predicting Recall: {recall:.2f}")
print(f"LR predicting F1 Score: {f1_score:.2f}")

"""###
- Naive Bayes
"""

from pyspark.ml.classification import NaiveBayes
nb = NaiveBayes()

# Measure training time
start_time = time.time()
predictor_nb = nb.fit(training)
end_time = time.time()

# Calculate training time
training_time_nb = end_time - start_time

# Print training time
print(f"Training time: {training_time_nb:.2f} seconds")

test_results_nb = predictor_nb.transform(testing)

test_results_nb.groupBy('prediction').count().show()

test_results_nb.groupBy('label', 'prediction').count().show()

acc_eval = MulticlassClassificationEvaluator()
acc_nb = acc_eval.evaluate(test_results_nb)
print("Accuracy of model at predicting: {}".format(acc_nb))

print("Before resampling data")
# Multiclass evaluator for precision, recall, F1-score, and accuracy
multi_evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction")

accuracy = multi_evaluator.evaluate(test_results_nb, {multi_evaluator.metricName: "accuracy"})
precision = multi_evaluator.evaluate(test_results_nb, {multi_evaluator.metricName: "weightedPrecision"})
recall = multi_evaluator.evaluate(test_results_nb, {multi_evaluator.metricName: "weightedRecall"})
f1_score = multi_evaluator.evaluate(test_results_nb, {multi_evaluator.metricName: "f1"})

# Display metrics
print(f"NB predicting Accuracy: {accuracy:.2f}")
print(f"NB predicting Precision: {precision:.2f}")
print(f"NB predicting Recall: {recall:.2f}")
print(f"NB predicting F1 Score: {f1_score:.2f}")

"""###
- RandomForest
"""

from pyspark.ml.classification import RandomForestClassifier

rf = RandomForestClassifier(labelCol="label", \
                            featuresCol="features", \
                            numTrees = 50, \
                            maxDepth = 5, \
                            maxBins = 64)

# Measure training time
start_time = time.time()
predictor_rf = rf.fit(training)
end_time = time.time()

# Calculate training time
training_time_rf = end_time - start_time

# Print training time
print(f"Training time: {training_time_rf:.2f} seconds")

test_results_rf = predictor_rf.transform(testing)

test_results_rf.groupBy('prediction').count().show()

# Create a confusion matrix
test_results_rf.groupBy('label', 'prediction').count().show()

acc_eval = MulticlassClassificationEvaluator()
acc_rf = acc_eval.evaluate(test_results_rf)
print("Accuracy of model at predicting: {}".format(acc_rf))

print("Before resampling data")
# Multiclass evaluator for precision, recall, F1-score, and accuracy
multi_evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction")

accuracy = multi_evaluator.evaluate(test_results_rf, {multi_evaluator.metricName: "accuracy"})
precision = multi_evaluator.evaluate(test_results_rf, {multi_evaluator.metricName: "weightedPrecision"})
recall = multi_evaluator.evaluate(test_results_rf, {multi_evaluator.metricName: "weightedRecall"})
f1_score = multi_evaluator.evaluate(test_results_rf, {multi_evaluator.metricName: "f1"})

# Display metrics
print(f"Random Forest predicting Accuracy: {accuracy:.2f}")
print(f"Random Forest predicting Precision: {precision:.2f}")
print(f"Random Forest predicting Recall: {recall:.2f}")
print(f"Random Forest predicting F1 Score: {f1_score:.2f}")

"""## Need to resample data"""

positive_df = training.filter(col("label") == 0)
negative_df = training.filter(col("label") == 1)
neutral_df = training.filter(col("label") == 2)
ratio_1 = int(positive_df.count()/negative_df.count())
ratio_2 = int(positive_df.count()/neutral_df.count())
print("ratio like/neutral: {}".format(ratio_1))
print("ratio like/not_like: {}".format(ratio_2))

# ratio1 = (ratio_1 -1)/2
# ratio2 = ratio_2/2

# resample negative
a1 = range(ratio_1)
# duplicate the minority rows
oversampled_negative_df = negative_df.withColumn("dummy",
                                                explode(array([lit(x) for x in a1])))\
                                                .drop('dummy')
# combine both oversampled minority rows and previous majority rows
combined_df = positive_df.unionAll(oversampled_negative_df)
combined_df.show(5)

combined_df.groupBy("label").count().show()

# resample neutral
a2 = range(ratio_2)
# duplicate the minority rows
oversampled_neutral_df = neutral_df.withColumn("dummy",
                                                explode(array([lit(x) for x in a2])))\
                                                .drop('dummy')
# combine both oversampled minority rows and previous majority rows
combined_df = combined_df.unionAll(oversampled_neutral_df)
combined_df.show(5)

combined_df.groupBy("label").count().show()

"""### Logistic Regression"""

predictor_lg1 = lg.fit(combined_df)

test_results_lg1 = predictor_lg1.transform(testing)

test_results_lg1.groupBy('label').count().show()

test_results_lg1.groupBy('label', 'prediction').count().show()

acc_eval = MulticlassClassificationEvaluator()
acc_lg1 = acc_eval.evaluate(test_results_lg1)
print("Accuracy of model at predicting: {}".format(acc_lg1))

print("After resampling data")
# Multiclass evaluator for precision, recall, F1-score, and accuracy
multi_evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction")

accuracy = multi_evaluator.evaluate(test_results_lg1, {multi_evaluator.metricName: "accuracy"})
precision = multi_evaluator.evaluate(test_results_lg1, {multi_evaluator.metricName: "weightedPrecision"})
recall = multi_evaluator.evaluate(test_results_lg1, {multi_evaluator.metricName: "weightedRecall"})
f1_score = multi_evaluator.evaluate(test_results_lg1, {multi_evaluator.metricName: "f1"})

# Display metrics
print(f"Logistic Regression predicting Accuracy: {accuracy:.2f}")
print(f"Logistic Regression predicting Precision: {precision:.2f}")
print(f"Logistic Regression predicting Recall: {recall:.2f}")
print(f"Logistic Regression predicting F1 Score: {f1_score:.2f}")

"""### Random Forest"""

predictor_rf1 = rf.fit(combined_df)

test_result_rf1 = predictor_rf1.transform(testing)

test_result_rf1.groupBy('label').count().show()

test_result_rf1.groupBy('label', 'prediction').count().show()

acc_eval = MulticlassClassificationEvaluator()
acc_rf1 = acc_eval.evaluate(test_result_rf1)
print("Accuracy of model at predicting: {}".format(acc_rf1))

print("After resampling data")
# Multiclass evaluator for precision, recall, F1-score, and accuracy
multi_evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction")

accuracy = multi_evaluator.evaluate(test_result_rf1, {multi_evaluator.metricName: "accuracy"})
precision = multi_evaluator.evaluate(test_result_rf1, {multi_evaluator.metricName: "weightedPrecision"})
recall = multi_evaluator.evaluate(test_result_rf1, {multi_evaluator.metricName: "weightedRecall"})
f1_score = multi_evaluator.evaluate(test_result_rf1, {multi_evaluator.metricName: "f1"})

# Display metrics
print(f"Random Forest predicting Accuracy: {accuracy:.2f}")
print(f"Random Forest predicting Precision: {precision:.2f}")
print(f"Random Forest predicting Recall: {recall:.2f}")
print(f"Random Forest predicting F1 Score: {f1_score:.2f}")

"""### Naive Bayer"""

from pyspark.ml.classification import NaiveBayes

nb = NaiveBayes()

predictor_nb1 = nb.fit(combined_df)

test_results_nb1 = predictor_nb1.transform(testing)

test_results_nb1.groupBy('label').count().show()

test_results_nb1.groupBy('label', 'prediction').count().show()

acc_eval = MulticlassClassificationEvaluator()
acc_nb1 = acc_eval.evaluate(test_results_nb1)
print("Accuracy of model at predicting: {}".format(acc_nb1))

print("After resampling data")
# Multiclass evaluator for precision, recall, F1-score, and accuracy
multi_evaluator = MulticlassClassificationEvaluator(labelCol="label", predictionCol="prediction")

accuracy = multi_evaluator.evaluate(test_results_nb1, {multi_evaluator.metricName: "accuracy"})
precision = multi_evaluator.evaluate(test_results_nb1, {multi_evaluator.metricName: "weightedPrecision"})
recall = multi_evaluator.evaluate(test_results_nb1, {multi_evaluator.metricName: "weightedRecall"})
f1_score = multi_evaluator.evaluate(test_results_nb1, {multi_evaluator.metricName: "f1"})

# Display metrics
print(f"Naive Bayes predicting Accuracy: {accuracy:.2f}")
print(f"Naive Bayes predicting Precision: {precision:.2f}")
print(f"Naive Bayes predicting Recall: {recall:.2f}")
print(f"Naive Bayes predicting F1 Score: {f1_score:.2f}")

print(f"Training time Logistic Regression: {training_time_log:.2f} seconds")
print(f"Training time Naive Bayes: {training_time_nb:.2f} seconds")
print(f"Training time Random Forest: {training_time_rf:.2f} seconds")
print("----------------")
print("Accuracy of model at Logistic Regression predicting: {}".format(acc_lg))
print("Accuracy of model at Naive Bayes predicting: {}".format(acc_nb))
print("Accuracy of model at Random Forest predicting: {}".format(acc_rf))
print("----------------")

print("After resampling data")
print("Accuracy of model at Logistic Regression predicting: {}".format(acc_lg1))
print("Accuracy of model at Naive Bayes predicting: {}".format(acc_nb1))
print("Accuracy of model at Random Forest predicting: {}".format(acc_rf1))