def is_eligible(age: int, has_license: bool, passed_exam: bool) -> bool:
    return age >= 18 and has_license and passed_exam
