"""Meta-research page: validation gate, PBO, calibration and allocations."""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from dashboard.api_client import APIClient
from dashboard.components.charts import bar_comparison, equity_curve_chart
from dashboard.components.metrics import kpi_row

TIMEFRAMES = ["M15", "M30", "H1", "H4", "D1"]


def render(client: APIClient) -> None:
    """Render the meta-research page."""
    st.title("🔬 Nghiên cứu & Kiểm định")

    reports = client.agent_reports()
    meta: Dict[str, Any] = reports.get("meta", {}) or {}
    research: Dict[str, Any] = reports.get("research", {}) or {}

    pipeline_tab, validation_tab, allocation_tab, calibration_tab = st.tabs(
        ["Dây chuyền nghiên cứu", "Kiểm định", "Phân bổ vốn", "Hiệu chuẩn"]
    )

    with pipeline_tab:
        st.subheader("Research Agent")
        kpi_row(
            [
                {"label": "Thế hệ", "value": research.get("generation", 0)},
                {"label": "Số ứng viên/thế hệ", "value": research.get("max_candidates", 0)},
                {"label": "Tỷ lệ đột biến", "value": research.get("mutation_rate", 0)},
                {"label": "Nhà cung cấp LLM", "value": research.get("llm_provider", "-")},
                {"label": "File AI đã tạo", "value": len(research.get("generated_files", []))},
            ]
        )

        hall_of_fame = research.get("hall_of_fame", [])
        if hall_of_fame:
            st.subheader("Bảng vàng ứng viên")
            frame = pd.DataFrame(
                [
                    {
                        "Chiến lược": item.get("strategy"),
                        "Cặp": item.get("symbol"),
                        "Điểm": item.get("score"),
                        "Sharpe": item.get("sharpe"),
                        "Số lệnh": item.get("trades"),
                    }
                    for item in hall_of_fame
                ]
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
            st.plotly_chart(
                bar_comparison(
                    [f"{item.get('strategy')} · {item.get('symbol')}" for item in hall_of_fame],
                    [float(item.get("score", 0)) for item in hall_of_fame],
                    "Điểm kiểm định của ứng viên",
                ),
                use_container_width=True,
            )
        else:
            st.info("Research Agent chưa hoàn thành thế hệ nào. Chu kỳ mặc định là 1 giờ.")

        if research.get("generated_files"):
            st.subheader("Chiến lược do AI sinh ra")
            for path in research["generated_files"][-10:]:
                st.code(path, language="text")

        if st.button("▶️ Chạy một thế hệ nghiên cứu ngay"):
            client.send_command("research_now", target="research")
            st.success("Đã gửi lệnh tới Research Agent. Kết quả xuất hiện sau khi chu kỳ kết thúc.")

    with validation_tab:
        st.subheader("Chạy kiểm định đầy đủ")
        available = client.strategies().get("available", [])
        symbols = [item["symbol"] for item in client.symbols()] or ["XAUUSD"]
        with st.form("run_validation"):
            columns = st.columns(4)
            name = columns[0].selectbox("Chiến lược", available or ["RSI"])
            symbol = columns[1].selectbox("Cặp", symbols)
            timeframe = columns[2].selectbox("Khung", TIMEFRAMES, index=2)
            quick = columns[3].checkbox("Chế độ nhanh (bỏ PBO)", value=False)
            submitted = st.form_submit_button("Chạy kiểm định", type="primary")
        if submitted:
            with st.spinner("Đang chạy WFA, PBO, hiệu chuẩn và kiểm tra bền vững..."):
                report = client.run_validation(
                    {"name": name, "symbol": symbol, "timeframe": timeframe, "quick": quick}
                )
            if report:
                st.session_state["last_validation"] = report
            else:
                st.error(f"Kiểm định thất bại: {client.last_error}")

        report = st.session_state.get("last_validation")
        if report:
            _render_validation_report(report)

        st.divider()
        st.subheader("Kết quả kiểm định của Meta Agent")
        validations = meta.get("validation_reports", {})
        if validations:
            frame = pd.DataFrame(
                [
                    {
                        "Chiến lược": key,
                        "Đạt": "✅" if item.get("passed") else "❌",
                        "Điểm": item.get("score"),
                        "Sharpe": item.get("sharpe"),
                        "PBO": item.get("pbo") if item.get("pbo") is not None else "chưa tính",
                        "WFA": item.get("wfa_efficiency"),
                        "Lý do": "; ".join(item.get("reasons", [])[:2]),
                    }
                    for key, item in validations.items()
                ]
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
        else:
            st.info("Meta Agent chưa chạy chu kỳ kiểm định nào.")

    with allocation_tab:
        st.subheader("Phân bổ vốn (Kelly có phạt bất định)")
        allocations: List[Dict[str, Any]] = meta.get("allocations", [])
        if allocations:
            frame = pd.DataFrame(
                [
                    {
                        "Chiến lược": item.get("strategy_name"),
                        "Cặp": item.get("symbol"),
                        "Kelly thô": item.get("raw_kelly"),
                        "Kelly đã phạt": item.get("penalised_kelly"),
                        "Hệ số vòng đời": item.get("lifecycle_multiplier"),
                        "Phân bổ": f"{float(item.get('allocation', 0)):.2%}",
                        "Vốn": item.get("capital"),
                        "Ghi chú": "; ".join(item.get("reasons", [])[:2]),
                    }
                    for item in allocations
                ]
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)
            deployed = [item for item in allocations if float(item.get("allocation", 0)) > 0]
            if deployed:
                st.plotly_chart(
                    bar_comparison(
                        [f"{item['strategy_name']} · {item['symbol']}" for item in deployed],
                        [float(item["allocation"]) for item in deployed],
                        "Tỷ trọng vốn được cấp",
                    ),
                    use_container_width=True,
                )
            else:
                st.warning(
                    "Không chiến lược nào đủ điều kiện cấp vốn — đây là hành vi đúng khi "
                    "chưa có bằng chứng thống kê về lợi thế."
                )
        else:
            st.info("Meta Agent chưa tính phân bổ vốn.")

    with calibration_tab:
        st.subheader("Hiệu chuẩn độ tin cậy")
        calibration = meta.get("calibration", {})
        if calibration and calibration.get("samples"):
            kpi_row(
                [
                    {"label": "Số mẫu", "value": calibration.get("samples", 0)},
                    {"label": "Sai số trung bình", "value": f"{calibration.get('mean_absolute_error', 0):.3f}"},
                    {"label": "Sai số lớn nhất", "value": f"{calibration.get('worst_bucket_error', 0):.3f}"},
                    {
                        "label": "Kết luận",
                        "value": "Đạt" if calibration.get("well_calibrated") else "Chưa đạt",
                    },
                ]
            )
        else:
            st.info("Chưa đủ dữ liệu để đánh giá hiệu chuẩn.")

        st.subheader("Nhật ký hệ thống")
        for note in (meta.get("notes") or [])[::-1]:
            st.text(note)


def _render_validation_report(report: Dict[str, Any]) -> None:
    """Render one full validation report."""
    passed = report.get("passed")
    st.markdown(f"### Kết quả: {'✅ ĐẠT' if passed else '❌ KHÔNG ĐẠT'}")
    baseline = report.get("baseline", {}).get("metrics", {})
    pbo = report.get("pbo", {})
    walk_forward = report.get("walk_forward", {})
    calibration = report.get("calibration", {})
    robustness = report.get("robustness", {})

    kpi_row(
        [
            {"label": "Điểm tổng", "value": f"{report.get('score', 0):.3f}"},
            {"label": "Sharpe", "value": f"{baseline.get('sharpe', 0):.2f}"},
            {
                "label": "PBO",
                "value": f"{pbo.get('pbo', 0):.2f}" if pbo.get("computed") else "chưa tính",
                "help": "Xác suất chiến lược chỉ khớp nhiễu quá khứ. Dưới 0.5 là chấp nhận được.",
            },
            {"label": "Hiệu suất WFA", "value": f"{walk_forward.get('efficiency', 0):.2f}"},
            {"label": "Sai số hiệu chuẩn", "value": f"{calibration.get('expected_calibration_error', 0):.3f}"},
        ]
    )

    if report.get("reasons"):
        st.warning("Lý do không đạt:\n\n" + "\n".join(f"- {reason}" for reason in report["reasons"]))

    folds = walk_forward.get("folds", [])
    if folds:
        st.subheader("Walk-Forward Analysis")
        frame = pd.DataFrame(folds)[
            ["fold", "train_sharpe", "test_sharpe", "test_return", "test_trades"]
        ].rename(
            columns={
                "fold": "Vòng",
                "train_sharpe": "Sharpe huấn luyện",
                "test_sharpe": "Sharpe kiểm tra",
                "test_return": "Lợi nhuận kiểm tra",
                "test_trades": "Số lệnh",
            }
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.plotly_chart(
            bar_comparison(
                [f"Vòng {fold['fold']}" for fold in folds],
                [fold["test_sharpe"] for fold in folds],
                "Sharpe ngoài mẫu theo từng vòng",
            ),
            use_container_width=True,
        )

    if robustness:
        st.subheader("Kiểm tra bền vững")
        rows = [
            ("Độ ổn định tham số", f"{robustness.get('parameter_stability', 0):.3f}"),
            ("Sharpe xấu nhất khi nhiễu tham số", f"{robustness.get('worst_perturbed_sharpe', 0):.2f}"),
            ("Độ nhạy chi phí", f"{robustness.get('cost_sensitivity', 0):.3f}"),
            ("Sống sót khi chi phí gấp đôi", "✅" if robustness.get("survives_double_costs") else "❌"),
        ]
        for regime, value in (robustness.get("regime_sharpes") or {}).items():
            rows.append((f"Sharpe chế độ {regime}", value))
        st.dataframe(
            pd.DataFrame(rows, columns=["Kiểm tra", "Kết quả"]),
            use_container_width=True,
            hide_index=True,
        )

    curve = report.get("baseline", {}).get("equity_curve")
    if curve:
        st.plotly_chart(
            equity_curve_chart(curve.get("timestamps", []), curve.get("values", [])),
            use_container_width=True,
        )
