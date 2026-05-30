from apii.checksums import iban_mod97, kuwait_mod11, luhn


def test_luhn_known_valid_saudi_nid():
    # Saudi National ID worked example from gulf-validator's
    # scripts/checksum-probe.py POSITIVE CONTROLS.
    assert luhn("1234567897") is True
    assert luhn("1010101010") is True


def test_luhn_rejects_off_by_one():
    # Flipping the check digit must break it. 1234567897 -> 1234567896.
    assert luhn("1234567896") is False


def test_luhn_rejects_non_digit():
    assert luhn("") is False
    assert luhn("12345abc90") is False
    # Arabic-Indic digits MUST be folded by the caller; raw rejection here
    # is the contract that prevents silently treating an unfolded string
    # as if every char were ASCII.
    assert luhn("١٢٣٤٥٦٧٨٩٧") is False


def test_luhn_rejects_all_zeros():
    # `sum > 0` guard — without it 0000…0000 passes the modular check
    # and would mask BBANs / placeholder digit runs as fake "valid" cards.
    assert luhn("0000000000000000") is False
    assert luhn("00000000") is False


def test_iban_mod97_valid_worked_examples():
    # Public worked-example IBANs harvested from gulf-validator's
    # data/iban.json + manual vetting. country-code + check digits move
    # to the END before mod-97; result 1 == valid.
    cases = [
        "SA0380000000608010167519",  # Al Rajhi (SA code 80)
        "AE070331234567890123456",   # Mashreq (AE code 033)
        "QA64SCBL000000000001375025601",  # Standard Chartered (QA)
        "KW43NBOK0000000000001000375231",  # NBK (KW)
        "OM810180000001299123456",        # NBO (OM code 018)
    ]
    for iban in cases:
        rearranged = iban[4:] + iban[:4]
        assert iban_mod97(rearranged) == 1, iban


def test_iban_mod97_rejects_non_alnum():
    # Contract from gulf-validator's TS implementation: any
    # non-alphanumeric byte yields the sentinel -1, not an exception.
    assert iban_mod97("SA03 9900 1111") == -1


def test_iban_mod97_synthetic_gold_iban_fails():
    # The repeated synthetic IBAN in tests/eval/gold/* — used to confirm
    # the two-tier (mod97 / context_fallback) design: shape-valid but
    # checksum-failing. Anything other than 1 is a fail.
    iban = "SA0399001111222233334444"
    assert iban_mod97(iban[4:] + iban[:4]) != 1


def test_kuwait_mod11_known_valid():
    # Worked examples from gulf-validator's checksum-probe.py.
    for cid in ["255031501232", "320022900029", "267110804563", "275062217902"]:
        assert kuwait_mod11(cid) is True, cid


def test_kuwait_mod11_rejects_off_by_one():
    # Flip the check digit on the first vector.
    assert kuwait_mod11("255031501233") is False


def test_kuwait_mod11_rejects_bad_length_or_prefix():
    # Length and century-marker enforcement matter — Civil IDs are always
    # 12 digits and start with 2 or 3.
    assert kuwait_mod11("25503150123") is False  # 11 digits
    assert kuwait_mod11("2550315012324") is False  # 13 digits
    assert kuwait_mod11("455031501232") is False  # bad century marker
