# tests/unit/test_build_medical_hallu.py
import importlib.util
import os
import random

import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_spec = importlib.util.spec_from_file_location("build_medical_hallu", os.path.join(ROOT, "ml/pipelines/build_medical_hallu.py"))
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)


@pytest.mark.parametrize("answer, expected", [
    ("Uống thuốc trước khi ăn.", "Uống thuốc sau khi ăn."),
    ("Thuốc làm giảm đau.", "Thuốc làm tăng đau."),
    ("Tăng cường vitamin C giúp tăng sức đề kháng.", "Tăng cường vitamin C giúp giảm sức đề kháng."),
    ("Triệu chứng không thuyên giảm trong 10 ngày.", None),  # compound word, not a direction
    ("Liều dùng như sau: 2 viên.", None),
])
def test_swap_direction_respects_compounds(answer, expected):
    assert b.swap_direction(answer, random.Random(0)) == expected


@pytest.mark.parametrize("answer, expected", [
    ("Không nên dùng cho trẻ em.", "Nên dùng cho trẻ em."),
    ("Thuốc nên uống sau ăn.", "Thuốc không nên uống sau ăn."),
    ("Thuốc dạng viên.", None),
])
def test_flip_negation(answer, expected):
    assert b.flip_negation(answer, random.Random(0)) == expected


def test_change_number_leaves_names_alone():
    assert b.change_number("Vitamin D3 và B12 hỗ trợ Covid-19.", random.Random(0)) is None
    assert b.change_number("Uống 500mg mỗi ngày.", random.Random(0)) != "Uống 500mg mỗi ngày."


def test_change_number_always_changes_value():
    out = b.change_number("Uống 2 viên mỗi 12 giờ.", random.Random(1))
    assert out and out != "Uống 2 viên mỗi 12 giờ."


def test_build_split_balances_labels_and_keeps_gold_for_no():
    rows = []
    for i in range(30):
        rows.append(dict(
            question_idx=str(i), question=f"Câu hỏi {i}?", topic=2, article_url=f"u{i}",
            context=f"Bài {i}. Thuốc A{i} nên uống trước khi ăn với liều 2 viên mỗi ngày cho người lớn.",
            answer=f"Thuốc A{i} nên uống trước khi ăn.",
        ))
    out = b.build_split(pd.DataFrame(rows), random.Random(0))
    assert out.label.value_counts().to_dict() == {"no": 10, "intrinsic": 10, "extrinsic": 10}
    gold = {f"Thuốc A{i} nên uống trước khi ăn." for i in range(30)}
    assert out[out.label == "no"].response.isin(gold).all()
    assert not out[out.label != "no"].response.isin(gold).any()
