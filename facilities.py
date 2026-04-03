"""연수원 목록 및 코드 매핑"""

# 연수원 이름 → ser_yeonsu_gbn 코드
# 코드는 사이트 HTML에서 추출; 일부는 런타임에 자동 탐지로 갱신됨
FACILITIES = {
    "속초수련원": "00003002",
    "서천연수원": "00003003",
    "수안보연수원": "00003004",
    "제주연수원": "00003005",
    "통영마리나연수원": "00003006",
    "경주연수원": "00003007",
    "엘리시안강촌연수원": "00003008",
    "블룸비스타연수원": "00003009",
    "여수히든베이연수원": "00003010",
    "여수베네치아연수원": "00003011",
}

# 역방향 매핑 (코드 → 이름)
CODE_TO_NAME = {v: k for k, v in FACILITIES.items()}


def get_facility_names() -> list:
    return list(FACILITIES.keys())


def get_facility_code(name: str) -> str | None:
    return FACILITIES.get(name)


def get_facility_name(code: str) -> str:
    return CODE_TO_NAME.get(code, code)


def update_facility_codes(parsed: dict):
    """사이트에서 파싱한 코드로 매핑 갱신"""
    for name, code in parsed.items():
        if name in FACILITIES:
            FACILITIES[name] = code
    CODE_TO_NAME.clear()
    CODE_TO_NAME.update({v: k for k, v in FACILITIES.items()})
