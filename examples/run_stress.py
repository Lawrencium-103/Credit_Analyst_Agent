"""Demo: run stress scenarios on the latest period of the SC client."""

from credit_agent.analysis.stress import run_stress
from credit_agent.spreading.loader import load_sc_workbook

WORKBOOK = "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"


def run_stress_demo() -> None:
    company = load_sc_workbook(WORKBOOK)
    base = company.latest()
    prior = company.prior()
    results = run_stress(base, prior)
    print(f"Stress testing: {company.entity_name} (base {base.period})\n")
    for r in results:
        print(f"--- {r.scenario}: {r.description} ---")
        print(f"  Rating: {r.base_rating} -> {r.stressed_rating} (downgrade {r.rating_downgrade} notch(es))")
        print(f"  PD: {r.base_pd * 100:.2f}% -> {r.stressed_pd * 100:.2f}%")
        for k in r.key_ratios_base:
            b, s = r.key_ratios_base[k], r.key_ratios_stressed[k]
            print(f"  {k}: {b:.2f} -> {s:.2f}")
        if r.breached_covenants:
            print(f"  BREACHED: {', '.join(r.breached_covenants)}")
        print()


if __name__ == "__main__":
    run_stress_demo()
