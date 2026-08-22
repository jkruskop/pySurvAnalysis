"""
Prepare survival analysis data from the RawData tab of the crowding experiment.

For each chamber (vial) within each treatment (UniqueName):
  - Each vial started with 2 flies.
  - Rows where Flag1 != 0 record observed deaths; Flag1 may count >1 death on
    that row. Each fly is one row (duplicate the row, once per death).
  - Remaining flies (2 minus total deaths in the vial) are added as right-censored
    rows at the last census time (max AgeH); one row per censored fly.

Output columns:
  age         – time of death or censoring (hours)
  treatment   – treatment group
  event       – 1 per individual (one observation per row)
  event_type  – 1 = observed death, 0 = right-censored
"""

import pandas as pd

# ── 1. Load the RawData sheet ────────────────────────────────────────────────
#INPUT_FILE = "mDilp235bx_Crowding_donor_20v40.xlsx"
INPUT_FILE = "wCS_mDilp235bx_Crowding_donor_20v40.xlsx"
FLIES_PER_VIAL = 2

df = pd.read_excel(INPUT_FILE, sheet_name="RawData")

# ── 2. Death rows (Flag1 != 0), then one row per fly ──────────────────────────
deaths = df.loc[df["Flag1"] != 0, ["AgeH", "Chamber", "UniqueName", "Flag1"]].copy()

# ── 3. Count deaths per chamber and find last census time ─────────────────────
deaths_per_chamber = deaths.groupby("Chamber")["Flag1"].sum().rename("n_deaths")

# Duplicate each raw death row Flag1 times so every individual has its own row.
deaths = deaths.loc[deaths.index.repeat(deaths["Flag1"].astype(int))].reset_index(
    drop=True
)
deaths["event"] = 1
deaths["event_type"] = 1
deaths = deaths.drop(columns=["Flag1"])
last_census = df.groupby("Chamber").agg(
    last_AgeH=("AgeH", "max"),
    UniqueName=("UniqueName", "first"),
).reset_index()

last_census = last_census.merge(deaths_per_chamber, on="Chamber", how="left")
last_census["n_deaths"] = last_census["n_deaths"].fillna(0).astype(int)

# ── 4. Build right-censored rows for surviving flies ──────────────────────────
censored_rows = []
for _, row in last_census.iterrows():
    n_censored = FLIES_PER_VIAL - row["n_deaths"]
    for _ in range(n_censored):
        censored_rows.append({
            "AgeH": row["last_AgeH"],
            "Chamber": row["Chamber"],
            "UniqueName": row["UniqueName"],
            "event": 1,
            "event_type": 0,
        })

censored = pd.DataFrame(censored_rows)

# ── 5. Combine deaths + censored, keep only needed columns ───────────────────
survival = pd.concat([deaths, censored], ignore_index=True)
survival = survival[["AgeH", "UniqueName", "event", "event_type"]].rename(
    columns={"AgeH": "age", "UniqueName": "treatment"}
)
survival = survival.sort_values(["treatment", "age"]).reset_index(drop=True)

# ── 6. Summary ────────────────────────────────────────────────────────────────
print("── Survival data summary ──")
print(f"Total observations: {len(survival)}")
print(f"  Observed deaths (event_type=1): {(survival['event_type'] == 1).sum()}")
print(f"  Censored (event_type=0): {(survival['event_type'] == 0).sum()}")
print()
print("By treatment:")
print(survival.groupby("treatment")["event_type"].value_counts().unstack(fill_value=0))
print()
print(survival.head(20))

# ── 7. Save to CSV ────────────────────────────────────────────────────────────
OUTPUT_FILE = "survival_data.csv"
survival.to_csv(OUTPUT_FILE, index=False)
print(f"\nSaved to {OUTPUT_FILE}")
