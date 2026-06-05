# Indonesian name generation with ethnic/regional diversity
# Based on actual Indonesian naming patterns by ethnicity

import random
from typing import Tuple

# Javanese names (most common in Indonesia ~40%)
JAVANESE_FIRST_MALE = [
    "Agus", "Bambang", "Budi", "Cahyo", "Darmawan", "Dwi", "Eko", "Galih",
    "Hadi", "Harjo", "Joko", "Kukuh", "Luhur", "Margono", "Nugroho", "Prasetyo",
    "Rahmat", "Setiawan", "Sugeng", "Suprapto", "Suryo", "Teguh", "Tri", "Wahyu",
    "Widodo", "Yanto", "Yudha", "Sigit", "Guntur", "Lanang", "Pangestu", "Wibowo",
]
JAVANESE_FIRST_FEMALE = [
    "Ayu", "Dewi", "Endang", "Fatimah", "Hartini", "Indah", "Kartini", "Lestari",
    "Mulyani", "Ning", "Putri", "Ratna", "Sari", "Sri", "Siti", "Suci", "Tuti",
    "Wahyuni", "Wati", "Wulan", "Yuni", "Astuti", "Rahayu", "Setyowati", "Murni",
]
JAVANESE_LAST = [
    "Santoso", "Wijaya", "Susanto", "Hidayat", "Prasetyo", "Nugroho", "Wibowo",
    "Setiawan", "Purnomo", "Sudirman", "Sulistyo", "Widodo", "Yulianto", "Hermawan",
    "Siswanto", "Wahyudi", "Hartono", "Suharto", "Sutrisno", "Kuswanto", "Suryono",
]

# Sundanese names (West Java ~15%)
SUNDANESE_FIRST_MALE = [
    "Asep", "Cecep", "Dede", "Encep", "Iwan", "Jajang", "Koswara", "Maman",
    "Nana", "Otong", "Ridwan", "Supriatna", "Tatang", "Ujang", "Yaya", "Zaenal",
    "Dadang", "Didin", "Eep", "Heri", "Iman", "Jeje", "Mang", "Obing", "Udin",
]
SUNDANESE_FIRST_FEMALE = [
    "Ai", "Cucu", "Enung", "Enok", "Entin", "Imas", "Lia", "Neng", "Neneng",
    "Rini", "Sinta", "Teti", "Tini", "Yanti", "Yuyun", "Susi", "Wiwi", "Yaya",
]
SUNDANESE_LAST = [
    "Supriatna", "Permana", "Hidayat", "Kurniawan", "Firmansyah", "Gunawan",
    "Saputra", "Koswara", "Sudrajat", "Suryana", "Ramdan", "Hernawan", "Sutisna",
]

# Batak names (North Sumatra ~3.5%)
BATAK_FIRST_MALE = [
    "Antonius", "Binsar", "Charles", "Donal", "Edison", "Frengky", "Gading",
    "Hotman", "Immanuel", "Jonatan", "Kristian", "Lamhot", "Mangapul", "Nathanael",
    "Oloan", "Parulian", "Rafael", "Samuel", "Tiopan", "Victor", "Willem",
]
BATAK_FIRST_FEMALE = [
    "Agnes", "Berliana", "Christina", "Debora", "Elisabeth", "Friska", "Gloria",
    "Helena", "Intan", "Junita", "Kristina", "Lamria", "Maria", "Novita",
    "Oktavia", "Patricia", "Ruth", "Sondang", "Tiurma", "Veronika", "Winda",
]
BATAK_LAST = [
    "Siahaan", "Simanjuntak", "Siregar", "Sitorus", "Sinaga", "Simatupang",
    "Napitupulu", "Hutabarat", "Panjaitan", "Manurung", "Tampubolon", "Pardede",
    "Sibarani", "Sagala", "Silalahi", "Ginting", "Tarigan", "Sembiring", "Karo",
]

# Chinese-Indonesian names (~2%)
CHINESE_INDO_FIRST_MALE = [
    "Agung", "Benny", "Cahyadi", "Danny", "Edwin", "Felix", "Giovanni", "Hendra",
    "Ivan", "Jimmy", "Kevin", "Liem", "Michael", "Nicholas", "Oscar", "Patrick",
    "Raymond", "Steven", "Tony", "Vincent", "William", "Yohanes", "Zeno",
]
CHINESE_INDO_FIRST_FEMALE = [
    "Angela", "Bella", "Cynthia", "Diana", "Elena", "Fiona", "Grace", "Hana",
    "Irene", "Jessica", "Kelly", "Linda", "Michelle", "Natalie", "Olivia",
    "Patricia", "Rachel", "Stephanie", "Tiffany", "Vanessa", "Wendy", "Yenny",
]
CHINESE_INDO_LAST = [
    "Tanoto", "Wijaya", "Halim", "Kurniawan", "Gunawan", "Susanto", "Hartono",
    "Lim", "Tan", "Ong", "Teo", "Chandra", "Wibowo", "Sutanto", "Budiman",
    "Tjandra", "Salim", "Tjakra", "Sugiarto", "Kusnadi", "Widjaja", "Tjokro",
]

# Minangkabau names (West Sumatra ~3%)
MINANG_FIRST_MALE = [
    "Aldi", "Azril", "Bagindo", "Datuak", "Efendi", "Fauzi", "Gusri", "Hakim",
    "Irfan", "Johan", "Khairul", "Lukman", "Marwan", "Nazir", "Omar", "Pandu",
    "Rasyid", "Syafri", "Taufik", "Usmar", "Valdi", "Wahid", "Yusran", "Zulkifli",
]
MINANG_FIRST_FEMALE = [
    "Ainun", "Bunga", "Chairani", "Desi", "Elsa", "Fitria", "Gusnita", "Hasna",
    "Indri", "Jelita", "Kartika", "Lusi", "Mira", "Nadya", "Okta", "Putri",
    "Rani", "Siska", "Tiara", "Ulfa", "Vira", "Winda", "Yola", "Zahra",
]
MINANG_LAST = [
    "Nasution", "Lubis", "Daulay", "Harahap", "Rangkuti", "Siregar", "Koto",
    "Tanjung", "Chaniago", "Piliang", "Sikumbang", "Dt. Rajo", "Batuah",
]

# Malay names (Riau, Jambi, South Sumatra ~5%)
MALAY_FIRST_MALE = [
    "Abdul", "Baharuddin", "Chairul", "Darmansyah", "Effendy", "Fachri",
    "Ghazali", "Hamdan", "Ibrahim", "Jamaluddin", "Kamaruddin", "Lukmanul",
    "Mahmud", "Nasaruddin", "Omar", "Putra", "Qadir", "Rahman", "Syahrul",
    "Tarmizi", "Usman", "Wahidin", "Yusuf", "Zainal",
]
MALAY_FIRST_FEMALE = [
    "Aisyah", "Badriah", "Chadijah", "Darlina", "Erniati", "Faridah", "Gustina",
    "Halimah", "Intan", "Juairiah", "Khadijah", "Latifah", "Maimunah", "Nurhayati",
    "Oktorina", "Putri", "Qomariah", "Rohana", "Salmah", "Tengku", "Ulfah",
]
MALAY_LAST = [
    "Abdullah", "Rahman", "Ahmad", "Syahputra", "Siregar", "Hakim", "Yusuf",
    "Lubis", "Sari", "Malik", "Putra", "Perdana", "Fadilah", "Maulana",
]

# Buginese/Makassarese names (South Sulawesi ~3%)
BUGIS_FIRST_MALE = [
    "Andi", "Burhanuddin", "Cakka", "Daeng", "Erwin", "Fadil", "Gusti",
    "Hasan", "Ilham", "Jufri", "Kahar", "La Ode", "Mappanyuki", "Nur",
    "Oddang", "Petta", "Qadir", "Rusdi", "Syamsuddin", "Tenri", "Udin",
]
BUGIS_FIRST_FEMALE = [
    "Andi", "Bau", "Citra", "Dara", "Erna", "Fatimah", "Gustina", "Hasni",
    "Indo", "Jumriah", "Kasmawati", "Lala", "Murni", "Nita", "Opu", "Puang",
]
BUGIS_LAST = [
    "Mappanyompa", "Colla", "Mattulada", "Mallombasi", "Arung", "Karaeng",
    "Petta", "Daeng", "Somba", "Puang", "Datu", "Tanete", "Bone", "Soppeng",
]

# Balinese names (Bali ~1.7%)
BALINESE_FIRST_MALE = [
    "Wayan", "Made", "Nyoman", "Ketut", "Putu", "Kadek", "Komang", "Gede",
    "Agung", "Bagus", "Cokorda", "Dewa", "Gusti", "Ida", "Ngurah",
]
BALINESE_FIRST_FEMALE = [
    "Wayan", "Made", "Nyoman", "Ketut", "Putu", "Kadek", "Komang", "Luh",
    "Ayu", "Desak", "Gusti", "Ida", "Ni", "Dayu",
]
BALINESE_LAST = [
    "Sudiana", "Suardika", "Widana", "Aryawan", "Putrawan", "Mahendra",
    "Wiratama", "Dharma", "Karna", "Yudha", "Darma", "Putra", "Sari",
]

# Ethnic group distribution (approximate Indonesian demographics)
ETHNIC_DISTRIBUTION = {
    "javanese": 0.40,
    "sundanese": 0.15,
    "batak": 0.035,
    "chinese": 0.02,
    "minang": 0.03,
    "malay": 0.05,
    "bugis": 0.03,
    "balinese": 0.017,
    "other": 0.198,  # Use Javanese as fallback
}

ETHNIC_NAMES = {
    "javanese": (JAVANESE_FIRST_MALE, JAVANESE_FIRST_FEMALE, JAVANESE_LAST),
    "sundanese": (SUNDANESE_FIRST_MALE, SUNDANESE_FIRST_FEMALE, SUNDANESE_LAST),
    "batak": (BATAK_FIRST_MALE, BATAK_FIRST_FEMALE, BATAK_LAST),
    "chinese": (CHINESE_INDO_FIRST_MALE, CHINESE_INDO_FIRST_FEMALE, CHINESE_INDO_LAST),
    "minang": (MINANG_FIRST_MALE, MINANG_FIRST_FEMALE, MINANG_LAST),
    "malay": (MALAY_FIRST_MALE, MALAY_FIRST_FEMALE, MALAY_LAST),
    "bugis": (BUGIS_FIRST_MALE, BUGIS_FIRST_FEMALE, BUGIS_LAST),
    "balinese": (BALINESE_FIRST_MALE, BALINESE_FIRST_FEMALE, BALINESE_LAST),
    "other": (JAVANESE_FIRST_MALE, JAVANESE_FIRST_FEMALE, JAVANESE_LAST),
}

# Province to likely ethnicity mapping
PROVINCE_ETHNICITY_MAP = {
    "DKI Jakarta": {"javanese": 0.35, "sundanese": 0.15, "chinese": 0.10, "batak": 0.08, "minang": 0.07, "other": 0.25},
    "Jawa Barat": {"sundanese": 0.75, "javanese": 0.15, "chinese": 0.05, "other": 0.05},
    "Jawa Timur": {"javanese": 0.80, "chinese": 0.05, "other": 0.15},
    "Jawa Tengah": {"javanese": 0.90, "chinese": 0.03, "other": 0.07},
    "Sumatera Utara": {"batak": 0.45, "malay": 0.20, "javanese": 0.15, "chinese": 0.08, "minang": 0.07, "other": 0.05},
    "Banten": {"sundanese": 0.50, "javanese": 0.25, "chinese": 0.10, "other": 0.15},
    "Sulawesi Selatan": {"bugis": 0.70, "javanese": 0.10, "other": 0.20},
    "Bali": {"balinese": 0.85, "javanese": 0.10, "other": 0.05},
    "Kalimantan Timur": {"javanese": 0.40, "bugis": 0.20, "batak": 0.10, "other": 0.30},
    "Sumatera Selatan": {"malay": 0.50, "javanese": 0.25, "chinese": 0.08, "other": 0.17},
    "Riau": {"malay": 0.60, "minang": 0.15, "javanese": 0.10, "chinese": 0.08, "other": 0.07},
    "Lampung": {"javanese": 0.60, "sundanese": 0.15, "malay": 0.10, "other": 0.15},
    "Sumatera Barat": {"minang": 0.90, "javanese": 0.05, "other": 0.05},
    "Nusa Tenggara Timur": {"other": 0.90, "javanese": 0.10},
    "Papua": {"other": 0.90, "javanese": 0.10},
    "Others": {"javanese": 0.40, "other": 0.60},
}


def select_ethnicity(province: str = None) -> str:
    """Select an ethnicity based on province or overall distribution."""
    if province and province in PROVINCE_ETHNICITY_MAP:
        dist = PROVINCE_ETHNICITY_MAP[province]
    else:
        dist = ETHNIC_DISTRIBUTION

    ethnicities = list(dist.keys())
    weights = list(dist.values())
    return random.choices(ethnicities, weights=weights, k=1)[0]


def generate_indonesian_name(province: str = None, gender: str = None) -> Tuple[str, str]:
    """
    Generate a realistic Indonesian name based on province and gender.

    Args:
        province: Province for ethnic distribution. If None, uses national average.
        gender: 'male' or 'female'. If None, randomly selected (50/50).

    Returns:
        Tuple of (full_name, gender)
    """
    if gender is None:
        gender = random.choice(["male", "female"])

    ethnicity = select_ethnicity(province)
    male_names, female_names, last_names = ETHNIC_NAMES.get(
        ethnicity, ETHNIC_NAMES["javanese"]
    )

    if gender == "male":
        first = random.choice(male_names)
    else:
        first = random.choice(female_names)

    last = random.choice(last_names)

    # Some ethnicities commonly have middle names or titles
    if ethnicity == "batak" and random.random() < 0.3:
        # Add clan marker
        full_name = f"{first} {last}"
    elif ethnicity == "bugis" and first == "Andi":
        # Andi is a nobility title, often paired with another name
        secondary = random.choice(male_names if gender == "male" else female_names)
        if secondary != "Andi":
            full_name = f"Andi {secondary} {last}"
        else:
            full_name = f"{first} {last}"
    elif ethnicity == "balinese" and random.random() < 0.4:
        # Balinese often use birth order names
        full_name = f"{first} {last}"
    else:
        # Standard first + last
        full_name = f"{first} {last}"

    return full_name, gender


# Legacy function for backward compatibility
def generate_indonesian_name_simple() -> str:
    """Generate a random Indonesian name (simple version for backward compat)."""
    name, _ = generate_indonesian_name()
    return name
