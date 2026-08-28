import pytest

from src.batch_edit.plan_value_contract import PlanValueContract


class _FirstContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


class _SecondContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


@pytest.mark.parametrize("error_type", [_FirstContractError, _SecondContractError])
def test_shared_plan_value_contract_rejects_publish_directives_identically(
    error_type,
) -> None:
    contract = PlanValueContract(error_type)

    with pytest.raises(error_type) as caught:
        contract.assert_no_publish_true({
            "nested": [{"save-and-publish": True}],
        })

    assert caught.value.reason_code == "PLAN_PUBLISH_FORBIDDEN"
    assert "plan.nested[0].save-and-publish" in str(caught.value)


def test_shared_plan_value_contract_keeps_validation_and_clone_canonical() -> None:
    contract = PlanValueContract(_FirstContractError)

    assert contract.positive_id_text("42", "shop_id") == "42"
    assert contract.sha256_text("a" * 64, "digest") == "A" * 64
    assert contract.stable_field_key("productPrice") == "productPrice"
    assert contract.clone({"b": 1, "a": [2]}) == {"a": [2], "b": 1}
