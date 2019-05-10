Dataset: TCGA

**Install Instructions**
See README.md

**Preprocessing**
Run commands from: https://github.com/Christensen-Lab-Dartmouth/PyMethylProcess/blob/master/example_scripts/TCGA.md

**Embedding using VAE**
Run 200 job hyperparameter scan for learning embeddings on torque (remove -t option to run local, same for prediction jobs below):  
```
methylnet-embed launch_hyperparameter_scan -cu -sc disease -t -mc 0.84 -b 1. -g -j 200 -a "module load python/3-Anaconda && source activate methylnet_pro2"
```
FINISH BELOW
Rerun top performing run to get final embeddings:
```
methylnet-embed launch_hyperparameter_scan -cu -sc disease -t -g -n 1 -b 1. -a "module load python/3-Anaconda && source activate methylnet_pro2"
```

**Predictions using Transfer Learning**
Run 200 job hyperparameter scan for learning predictions on torque:
```
methylnet-predict launch_hyperparameter_scan -cu -ic disease -cat -t -g -mc 0.70 -j 400 -a "module load python/3-Anaconda && source activate methylnet_pro2"
```
Rerun top performing run to get final predictions:
```
methylnet-predict launch_hyperparameter_scan -cu -ic disease -cat -t -g -n 1 -a "module load python/3-Anaconda && source activate methylnet_pro2"
```

**Plot Embedding and Prediction Results**
```
methylnet-predict classification_report
methylnet-visualize plot_training_curve
methylnet-visualize plot_training_curve -t embeddings/training_val_curve.p -vae -o results/embed_training_curve.png
methylnet-visualize plot_roc_curve
```

**MethylNet Interpretations**
If using torque:  
```
methylnet-torque run_torque_job -c "methylnet-interpret produce_shapley_data -mth gradient -ssbs 30 -ns 300 -bs 100 -col disease -r 0 -rt 30 -nf 1000 -c" -gpu -a "module load python/3-Anaconda && source activate methylnet_pro2" -q gpuq -t 24 -n 1
```
Else (running with GPU 0):  
```
CUDA_VISIBLE_DEVICES=0 methylnet-interpret produce_shapley_data -mth gradient -ssbs 30 -ns 300 -bs 100 -col disease -r 0 -rt 30 -nf 4000 -c
```

Extract spreadsheet of top overall CpGs:
```
methylnet-interpret return_shap_values -log -c all -hist -o interpretations/shap_results/ &
methylnet-interpret return_shap_values -log -c all -hist -abs -o interpretations/abs_shap_results/ &
```

Plot bar chart of top CpGs:
```

```

Find H-Cluster of CpGs between Disease Subtypes (FINISH):
```
methylnet-interpret regenerate_top_cpgs -nf 4000 && methylnet-interpret split_hyper_hypo_methylation -thr original -s ./interpretations/shapley_explanations/shapley_reduced_data.p && methylnet-interpret shapley_jaccard -c all -ov -s ./interpretations/shapley_explanations/shapley_data_by_methylation/hypo_shapley_data.p -o ./interpretations/shapley_explanations/top_cpgs_jaccard/hypo/ && pymethyl-visualize plot_heatmap -m similarity -fs .6 -i ./interpretations/shapley_explanations/top_cpgs_jaccard/hypo/all_jaccard.csv -o ./interpretations/shapley_explanations/top_cpgs_jaccard/all_jaccard.png -x -y -c &


pymethyl-visualize plot_heatmap -m distance -fs .6 -i interpretations/shap_results/returned_shap_values_corr_dist.csv -o ./interpretations/shap_results/distance_cpgs.png -x -y -c &
pymethyl-visualize plot_heatmap -m distance -fs .6 -i interpretations/abs_shap_results/returned_shap_values_corr_dist.csv -o ./interpretations/abs_shap_results/distance_cpgs.png -x -y -c &

```

Train Support Vector Machine Model and Evaluate for Comparison (copy TCGA_SVC.py example script):
```
python TCGA_SVC.py -n 24 -o disease -tr train_val_test_sets/train_methyl_array.pkl -v train_val_test_sets/val_methyl_array.pkl -tt train_val_test_sets/test_methyl_array.pkl -s &

python
>>> df=pd.read_csv("SklearnPredictions.csv")
>>> accuracy_score(df['y_pred'],df['y_true'])
0.8389021479713604
```

Find genomic context of these CpGs:
```

```

Run enrichment test with LOLA:
```

```

Plot results:
```

```


* python model_interpretability.py shapley_jaccard -c all -i -ov
* pymethyl-visualize plot_heatmap -m similarity -fs .2 -i ./interpretations/shapley_explanations/top_cpgs_jaccard/all_jaccard.csv -o ./interpretations/shapley_explanations/top_cpgs_jaccard/all_jaccard.png -x -y -c &
* python model_interpretability.py reduce_top_cpgs -nf 1000 && python model_interpretability.py split_hyper_hypo_methylation -s ./interpretations/shapley_explanations/shapley_reduced_data.p
* python model_interpretability.py shapley_jaccard -c all -i -ov -s ./interpretations/shapley_explanations/shapley_data_by_methylation/hypo_shapley_data.p -o ./interpretations/shapley_explanations/top_cpgs_jaccard/hypo/
* pymethyl-visualize plot_heatmap -m similarity -fs .2 -i ./interpretations/shapley_explanations/top_cpgs_jaccard/hypo/all_jaccard.csv -o ./interpretations/shapley_explanations/top_cpgs_jaccard/all_hypo_jaccard.png -x -y -c &
* python model_interpretability.py shapley_jaccard -c all -i -ov -s ./interpretations/shapley_explanations/shapley_data_by_methylation/hyper_shapley_data.p -o ./interpretations/shapley_explanations/top_cpgs_jaccard/hyper/
* pymethyl-visualize plot_heatmap -m similarity -fs .2 -i ./interpretations/shapley_explanations/top_cpgs_jaccard/hyper/all_jaccard.csv -o ./interpretations/shapley_explanations/top_cpgs_jaccard/all_hyper_jaccard.png -x -y -c &


* nohup time python random_forest_test.py -tr train_val_test_sets/train_methyl_array.pkl -v train_val_test_sets/val_methyl_array.pkl -tt train_val_test_sets/test_methyl_array.pkl -o Disease_State -c -n 400 &

* python TCGA_ElasticNet.py -n 1 -o disease -tr train_val_test_sets/train_methyl_array.pkl -v train_val_test_sets/val_methyl_array.pkl -tt train_val_test_sets/test_methyl_array.pkl

*