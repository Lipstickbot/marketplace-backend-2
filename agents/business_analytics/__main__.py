from argparse import ArgumentParser
from dataclasses import asdict
import json
from pathlib import Path
import sys

from . import analyze, choose_language
from .dimensions import DIMENSION_ALIASES
from .metrics import DatasetError, MAX_CSV_BYTES
from .report import language_index

ERRORS = {
    "size": ("Размер файла должен быть не больше 128 КиБ.", "Файл көлемі 128 КиБ-тан аспауы керек.", "The file must be at most 128 KiB."),
    "format": ("Проверьте кодировку UTF-8, кавычки и разделители.", "UTF-8 кодтауын, тырнақшалар мен бөлгіштерді тексеріңіз.", "Check UTF-8 encoding, quoting and separators."),
    "columns": ("Укажите уникальные заголовки и хотя бы один известный показатель.", "Бірегей тақырыптар мен кемінде бір белгілі көрсеткішті енгізіңіз.", "Use unique headers and include at least one supported metric."),
    "width": ("Число полей должно совпадать с числом заголовков.", "Өріс саны тақырыптар санымен сәйкес болуы керек.", "The field count must match the number of headers."),
    "rows": ("Допустимо до 5000 строк данных.", "Дерек жолдарының саны 5000-нан аспауы керек.", "The dataset may contain up to 5,000 data rows."),
    "number": ("Проверьте число, десятичный разделитель и знак.", "Санды, ондық бөлгішті және таңбасын тексеріңіз.", "Check the number, decimal separator and sign."),
    "date": ("Используйте дату YYYY-MM-DD или месяц YYYY-MM.", "Күн үшін YYYY-MM-DD, ай үшін YYYY-MM пішімін қолданыңыз.", "Use YYYY-MM-DD for dates or YYYY-MM for months."),
    "currency": ("Укажите трёхбуквенный код валюты, например KZT.", "KZT сияқты үш әріптік валюта кодын енгізіңіз.", "Use a three-letter currency code such as KZT."),
    "mixed_currency": ("Укажите одну валюту во всех строках или уберите столбец currency.", "Барлық жолда бір валютаны көрсетіңіз немесе currency бағанын алып тастаңыз.", "Use one currency in all rows or remove the currency column."),
    "mixed_dates": ("Используйте единый формат периода во всех строках.", "Барлық жолда кезеңнің бір пішімін қолданыңыз.", "Use one period format throughout the dataset."),
    "period_format": ("Для выбора периода укажите месяц, например 2026-01.", "Кезеңді таңдау үшін айды көрсетіңіз, мысалы 2026-01.", "Select a month, for example 2026-01."),
    "period_missing": ("Указанного месяца нет в таблице. Проверьте колонку period.", "Көрсетілген ай кестеде жоқ. period бағанын тексеріңіз.", "The requested month is absent. Check the period column."),
    "period_ambiguous": ("Этот месяц встречается в файле за несколько лет. Укажите год, например 2026-01.", "Бұл ай файлда бірнеше жылда кездеседі. Жылды көрсетіңіз, мысалы 2026-01.", "This month appears in more than one year. Specify the year, for example 2026-01."),
    "period_limit": ("Выберите один месяц для сводки или два для сравнения.", "Қорытынды үшін бір айды немесе салыстыру үшін екі айды таңдаңыз.", "Select one month for a summary or two for comparison."),
    "period_order": ("Укажите начало диапазона раньше конца или в том же месяце.",
                     "Аралықтың басы соңынан кейін болмауы керек.",
                     "The range start must be on or before its end."),
    "group_dimension": ("Выберите одну колонку разбивки из region, channel, product, category или sku.",
                        "Бөлу үшін region, channel, product, category немесе sku бағанының бірін таңдаңыз.",
                        "Select one breakdown column from region, channel, product, category or sku."),
    "group_missing": ("Для разбивки добавьте в CSV колонку {field}.",
                      "Топтау үшін CSV файлына {field} бағанын қосыңыз.",
                      "Add the {field} column to the CSV to group the results."),
    "group_multiple": ("Выберите одну колонку разбивки на запрос.",
                       "Бір сұрауда топтау үшін бір бағанды таңдаңыз.",
                       "Choose one breakdown column per request."),
    "group_requires_data": ("Для разбивки приложите CSV.", "Топтау үшін CSV тіркеңіз.", "Supply a CSV to group the results."),
    "empty": ("Добавьте хотя бы одну строку с числовыми данными.", "Кемінде бір сандық дерек жолын қосыңыз.", "Add at least one row with numeric data."),
    "multiple": ("Выберите одну таблицу для запроса.", "Сұрау үшін бір кесте таңдаңыз.", "Use one dataset per question."),
    "question_size": ("В запросе допустимо до 8000 символов.", "Сұрау 8000 таңбадан аспауы керек.", "The question may contain up to 8,000 characters."),
    "file": ("Не удалось открыть файл.", "Файлды ашу мүмкін болмады.", "Could not open the file."),
}


def read_dataset(path: Path) -> str:
    with path.open("rb") as handle:
        data = handle.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise DatasetError("size")
    return data.decode("utf-8-sig")


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Локальный бизнес-аналитик для CSV и вопросов о показателях.")
    parser.add_argument("question", nargs="?", default="", help="вопрос о бизнес-показателях")
    dataset = parser.add_mutually_exclusive_group()
    dataset.add_argument("--csv", type=Path, help="путь к таблице CSV или TSV в UTF-8")
    dataset.add_argument("--example", action="store_true", help="проанализировать встроенный пример")
    parser.add_argument("--lang", choices=("auto", "ru", "kk", "en"), default="auto", help="язык ответа")
    parser.add_argument("--group-by", choices=tuple(DIMENSION_ALIASES), help="колонка для разбивки итогов")
    parser.add_argument("--json", action="store_true", help="вывести структурированный результат")
    args = parser.parse_args(argv)
    if not (args.question or args.csv or args.example or args.group_by):
        parser.print_help()
        return 0
    path = Path(__file__).with_name("example.csv") if args.example else args.csv
    question = args.question or ("Почему выручка растёт, а маржа падает?" if args.example else "")
    try:
        result = analyze(question, csv_text=read_dataset(path) if path else None, language=args.lang, group_by=args.group_by)
    except (DatasetError, OSError, UnicodeError) as error:
        if not isinstance(error, DatasetError):
            error = DatasetError("file" if isinstance(error, OSError) else "format")
        if args.json:
            payload = {"error": error.code, "row": error.row}
            if error.field is not None:
                payload["field"] = error.field
            print(json.dumps(payload), file=sys.stderr)
        else:
            lang = language_index(choose_language(question, args.lang))
            location = f"{('Строка', 'Жол', 'Row')[lang]} {error.row}. " if error.row else ""
            print(location + ERRORS[error.code][lang].format(field=error.field), file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2) if args.json else result.answer)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
