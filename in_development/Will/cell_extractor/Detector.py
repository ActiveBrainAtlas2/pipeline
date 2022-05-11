from cell_extractor.Predictor import Predictor
import numpy as np

class Detector():
    def __init__(self,model=None,predictor:Predictor=None):
        self.model = model
        self.predictor = predictor
    
    def calculate_scores(self,features):
        _,_,all=self.get_train_and_test(features)
        labels=all.get_label()
        scores=np.zeros([features.shape[0],len(self.model)])
        for i in range(len(self.model)):
            bst=self.model[i]
            scores[:,i] = bst.predict(all, iteration_range=[1,bst.best_ntree_limit], output_margin=True)
        _mean=np.mean(scores,axis=1)
        _std=np.std(scores,axis=1)
        return scores,labels,_mean,_std

    def get_prediction(self,_mean,_std):
        predictions=[]
        for mean,std in zip(_mean,_std):
            p=self.predictor.decision(float(mean),float(std))
            predictions.append(p)
        return np.array(predictions)