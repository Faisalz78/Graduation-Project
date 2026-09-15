SAUDI_REGIONS = {
    "RIYADH": "الرياض",
    "MAKKAH": "مكة المكرمة",
    "MADINAH": "المدينة المنورة",
    "QASSIM": "القصيم",
    "EASTERN": "المنطقة الشرقية",
    "ASIR": "عسير",
    "TABUK": "تبوك",
    "HAIL": "حائل",
    "NORTHERN_BORDERS": "الحدود الشمالية",
    "JAZAN": "جازان",
    "NAJRAN": "نجران",
    "BAHAH": "الباحة",
    "JOUF": "الجوف",
}


def validate_region_code(value):
    if value is not None and value not in SAUDI_REGIONS:
        raise ValueError("اختر منطقة سعودية معتمدة من القائمة.")
    return value
