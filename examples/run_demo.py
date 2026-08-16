"""Demo: run the full analysis pipeline on the sample client."""

from credit_agent import compute_ratios, rate
from credit_agent.risk.rating import RatingBand
from examples.sample_financials import GREEN_SOLUTIONS


def run_demo() -> None:
    cf = GREEN_SOLUTIONS
    print(f"\n=== Credit Analysis: {cf.entity_name} ({cf.currency}) ===\n")
    for i, period in enumerate(cf.periods):
        prior = cf.periods[i - 1] if i > 0 else None
        ratios = compute_ratios(period, prior)
        rating = rate(ratios)
        print(f"--- {period.period} ---")
        for r in ratios.results:
            if r.value is None:
                continue
            val = f"{r.value:.2%}" if r.unit == "%" else f"{r.value:.2f}{r.unit}"
            flag = "" if r.within_healthy_band is None else ("  OK" if r.within_healthy_band else "  !!")
            print(f"  {r.label:<42} {val:>10}{flag}")
        print(f"  RATING: {rating.band.value}  (composite {rating.composite_score}, PD {rating.pd_estimate:.2%})")
        print()


if __name__ == "__main__":
    run_demo()
