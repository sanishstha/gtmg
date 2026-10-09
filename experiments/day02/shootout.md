# Day 2 model shootout

Thirty hand-labeled documents, three models, ninety calls. The exam does not write to Postgres.

```
Metric           Cheap      Mid        Strong     
Accuracy         60.0%      93.3%      96.7%      
Schema validity  100.0%     100.0%     100.0%     
Recall           45.5%      95.5%      100.0%     
Precision        100.0%     100.0%     100.0%     
Avg latency      1256 ms    1524 ms    1369 ms    
Cost/run         $0.000066  $0.000307  $0.001606  
Cost/correct     $0.000109  $0.000329  $0.001661  
```

Accuracy is strict: the extracted set must match the labeled pairs with nothing left over. Recall ignores extra events. Precision asks only whether a document that produced an event was a document that had one. Cost per correct is total spend divided by strict correct cases.
