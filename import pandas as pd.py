import pandas as pd

df = pd.read_excel("C:/Users/kande/Downloads/monthly_hourly_load_values_2026.xlsx")

hourly_sum = (
    df.groupby("hour", as_index=False)["value"]
      .sum()
)

