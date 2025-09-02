
from typing import List

import numpy as np
from pydantic import BaseModel, Field

def calculate_trend(scores: List[float]) -> float:
      """ Calculates the performance trend of a protein over time. Uses linear regression to find the slope of the scores. A positive slope indicates improvement, negative indicates degradation."""
      if len(scores) < 2:
            return 0.0
      y = np.array(scores)
      x = np.arange(len(y))
      slope, _ = np.polyfit(x, y, 1)
      return slope

def calculate_volatility(scores: List[float]) -> float:
      """Calculates the volatility (stability) of a protein's performance. Uses standard deviation. A higher value means more instability."""
      if len(scores) < 2:
            return 0.0
      return np.std(scores)