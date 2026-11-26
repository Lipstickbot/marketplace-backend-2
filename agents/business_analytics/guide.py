"""Business methods used when a question needs guidance or more data."""

GUIDE = {
    "profit": (
        "Прибыль в этой модели = выручка − учтённые затраты. Маржа = прибыль ÷ выручка × 100% при положительной выручке. Проверьте, входят ли в затраты доставка, возвраты и комиссии. Для поиска причины сравните долю затрат по товарам и каналам за одинаковые периоды.",
        "Бұл үлгіде пайда = түсім − есепке алынған шығын. Түсім оң болғанда маржа = пайда ÷ түсім × 100%. Жеткізу, қайтарым және комиссия шығынға кіре ме, соны тексеріңіз. Себебін анықтау үшін бірдей кезеңдердегі тауарлар мен арналардың шығын үлесін салыстырыңыз.",
        "In this model, profit = revenue − reported costs. With positive revenue, margin = profit ÷ revenue × 100%. Check whether costs include fulfillment, returns and fees. Compare cost shares by product and channel over comparable periods to investigate the change.",
    ),
    "sales": (
        "Разложите выручку на количество заказов и средний чек. Средний чек = выручка ÷ число заказов при положительном числе заказов. Сравните показатели по товарам, каналам и новым или повторным покупкам. Отдельно проверьте скидки, отмены и возвраты.",
        "Түсімді тапсырыс саны мен орташа чекке бөліп қараңыз. Тапсырыс саны оң болса, орташа чек = түсім ÷ тапсырыс саны. Тауарларды, арналарды, жаңа және қайталама сатып алуларды салыстырыңыз. Жеңілдіктерді, жойылған және қайтарылған тапсырыстарды бөлек тексеріңіз.",
        "Break revenue down into order volume and average order value. With positive order volume, average order value = revenue ÷ orders. Compare products, channels and new versus returning buyers. Check discounting, cancellations and returns separately.",
    ),
    "conversion": (
        "Конверсия = конверсии ÷ визиты × 100% при положительном числе визитов. Задайте одно целевое действие и одинаковый способ учёта для всех периодов. Проверьте долю переходов между этапами воронки по каналу и устройству.",
        "Кірулер саны оң болса, конверсия = конверсиялар ÷ кірулер × 100%. Бір мақсатты әрекетті таңдап, барлық кезеңде бірдей есептеу әдісін қолданыңыз. Арна мен құрылғы бойынша воронка кезеңдері арасындағы өту үлесін тексеріңіз.",
        "With positive visits, conversion rate = conversions ÷ visits × 100%. Use one target action and the same counting method across periods. Check step-to-step funnel rates by channel and device.",
    ),
    "marketing": (
        "ROAS = выручка, отнесённая к рекламе, ÷ расходы на рекламу. Для сравнения кампаний используйте единое окно атрибуции и валюту. Чтобы оценить вклад в прибыль, отдельно учтите себестоимость, комиссию и доставку.",
        "ROAS = жарнамаға жатқызылған түсім ÷ жарнама шығыны. Науқандарды салыстырғанда бірдей атрибуция кезеңі мен валютаны қолданыңыз. Пайдаға әсерін бағалау үшін өзіндік құнды, комиссияны және жеткізуді бөлек есептеңіз.",
        "ROAS = ad-attributed revenue ÷ ad spend. Use the same attribution window and currency across campaigns. To assess contribution to profit, also account for unit costs, fees and fulfillment.",
    ),
    "quality": (
        "Проверьте единицы, валюту, формат дат и смысл одной строки. Пустую ячейку сохраните как пропуск, а реальный ноль передайте числом. Сверьте итог с исходной системой. Для проверки дублей используйте ключ операции или набор полей, который должен быть уникальным.",
        "Өлшем бірлігін, валютаны, күн пішімін және бір жолдың нені білдіретінін тексеріңіз. Бос ұяшықты бос қалдырып, нақты нөлді санмен көрсетіңіз. Жиынтықты бастапқы жүйемен салыстырыңыз. Қайталанған жолдарды операцияның бірегей кілті арқылы тексеріңіз.",
        "Check units, currency, dates and what each row represents. Keep blanks as missing values and record true zeros as numbers. Reconcile the total with the source system. Use a transaction key or a field combination that should be unique to check duplicates.",
    ),
    "report": (
        "Начните с решения, которое должен принять читатель. Для каждого KPI запишите определение, источник, период, факт и базу сравнения. Выделите существенные изменения, отметьте ограничения, укажите следующий шаг и ответственного.",
        "Оқырман қабылдауы керек шешімнен бастаңыз. Әр KPI үшін анықтаманы, дереккөзді, кезеңді, нақты мәнді және салыстыру негізін жазыңыз. Маңызды өзгерістерді, шектеулерді, келесі қадамды және жауапты адамды көрсетіңіз.",
        "Start with the decision the reader needs to make. For every KPI, record its definition, source, period, actual value and baseline. Flag material changes and limitations, then assign a next step and an owner.",
    ),
    "periods": (
        "Сравнивайте одинаковые по охвату периоды и единые определения показателей. Темп роста = (текущее значение − прошлое) ÷ прошлое × 100% при положительной базе. Изменения долей показывайте в процентных пунктах. Для проверки сезонности сравните те же месяцы прошлых лет.",
        "Қамтуы және көрсеткіш анықтамалары бірдей кезеңдерді салыстырыңыз. Алдыңғы мән оң болса, өсу қарқыны = (ағымдағы мән − алдыңғы мән) ÷ алдыңғы мән × 100%. Үлестің өзгерісін пайыздық тармақпен көрсетіңіз. Маусымдықты тексеру үшін өткен жылдардың сол айларын салыстырыңыз.",
        "Compare periods with the same coverage and consistent metric definitions. With a positive baseline, growth = (current − previous) ÷ previous × 100%. Show changes in rates in percentage points. Compare the same months in earlier years to check seasonality.",
    ),
    "retention": (
        "Сформируйте когорты по неделе регистрации или первой покупки. Удержание = клиенты из когорты, активные в выбранный день или интервал ÷ исходный размер когорты. Задайте событие активности и сравнивайте группы на одинаковом сроке жизни. Для оттока подписок берите клиентов, активных на начало периода, и считайте тех из них, кто прекратил подписку к концу периода.",
        "Тіркелген немесе алғаш сатып алған апта бойынша когорталар құрыңыз. Таңдалған мерзімдегі сақталу = сол мерзімде белсенді когорта клиенттері ÷ когортаның бастапқы саны. Белсенділік оқиғасын анықтап, топтарды бірдей жаста салыстырыңыз. Жазылымнан кетуді есептеу үшін кезең басында белсенді болып, кезең соңына дейін жазылымын тоқтатқан клиенттерді санаңыз.",
        "Group customers by first purchase or signup week. Retention at a given age = active customers at that age ÷ original cohort size. Define activity and compare cohorts at the same age. For subscription churn, start from accounts active at the beginning and count which of those had stopped by the end.",
    ),
    "inventory": (
        "Дни запаса = текущий доступный остаток ÷ среднедневной спрос. Сравните покрытие со сроком поставки и разбросом спроса. Оборачиваемость за период = себестоимость реализованного товара ÷ средний запас по себестоимости. Считайте по SKU и складу. Проверьте дни отсутствия товара, когда продажи могли занижать спрос.",
        "Қордың жететін күні = қолжетімді қалдық ÷ орташа күндік сұраныс. Нәтижені жеткізу мерзімімен және сұраныстың өзгерісімен салыстырыңыз. Кезеңдегі айналым = сатылған тауардың өзіндік құны ÷ қордың өзіндік құн бойынша орташа мәні. Әр SKU мен қойманы бөлек есептеңіз. Тауар болмаған күндері сату сұранысты төмен көрсеткен болуы мүмкін.",
        "Days of cover = available units ÷ average daily demand. Compare cover with replenishment lead time and demand variability. Period inventory turnover = cost of goods sold ÷ average inventory at cost. Segment by SKU and warehouse. Check stockout days because sales may understate unmet demand.",
    ),
    "plan": (
        "Возьмите утверждённый план и факт за один период и в одних единицах. Отклонение = факт − план. При положительном плане процент отклонения = отклонение ÷ план × 100%. При нулевом плане покажите разницу в исходных единицах. По выручке проверьте вклад цены, объёма и ассортимента, а по расходам отдельно оцените перерасход и изменение объёма работ.",
        "Бір кезеңге арналған бекітілген жоспар мен нақты көрсеткішті бір өлшемде алыңыз. Ауытқу = нақты мән − жоспар. Жоспар оң болса, пайыздық ауытқу = ауытқу ÷ жоспар × 100%. Жоспар нөл болса, айырманы бастапқы бірлікпен көрсетіңіз. Түсім үшін баға, көлем және тауар құрамы әсерін, шығын үшін артық жұмсау мен жұмыс көлемінің өзгерісін тексеріңіз.",
        "Use the approved plan and actuals for the same period and units. Variance = actual − plan. For a positive plan, percent variance = variance ÷ plan × 100%. With a zero plan, report the absolute difference in the original units. For revenue, investigate price, volume and mix. For expenses, separate overspending from changes in activity volume.",
    ),
    "experiment": (
        "Уточните единицу случайного распределения, основную метрику и минимальный эффект, важный для решения. Проверьте баланс трафика и полноту событий. Покажите разницу с доверительным интервалом и проверьте защитные метрики. Если тест идёт по заранее фиксированному плану, дождитесь заданного объёма данных или срока перед окончательным выводом.",
        "Кездейсоқ бөлу бірлігін, негізгі көрсеткішті және шешімге маңызды ең кіші әсерді анықтаңыз. Трафиктің бөлінуін және оқиғалардың толықтығын тексеріңіз. Айырманы сенімділік аралығымен көрсетіп, қосымша бақылау көрсеткіштерін тексеріңіз. Тест жоспары алдын ала бекітілсе, қорытындыға дейін белгіленген дерек көлемін немесе мерзімді күтіңіз.",
        "Identify the randomization unit, primary metric and smallest effect worth acting on. Check traffic allocation and event coverage. Report the difference with a confidence interval and review guardrail metrics. For a fixed-horizon design, wait for the prespecified duration or sample before drawing a final conclusion.",
    ),
    "unit_economics": (
        "Вклад с заказа = выручка с заказа − переменные затраты на него. При одинаковом положительном вкладе точка безубыточности в заказах = постоянные затраты за период ÷ вклад с заказа, с округлением вверх. CAC = затраты на привлечение ÷ число новых клиентов за сопоставимый период. Для окупаемости CAC сравните стоимость привлечения с накопленным вкладом клиента после переменных затрат.",
        "Тапсырыс үлесі = тапсырыс түсімі − оның айнымалы шығыны. Үлес оң болса, шығынсыздыққа қажет тапсырыс саны = кезеңнің тұрақты шығыны ÷ бір тапсырыс үлесі, нәтижені жоғары қарай дөңгелектеңіз. CAC = салыстырмалы кезеңдегі тарту шығыны ÷ жаңа клиент саны. Өтелуді есептеу үшін CAC-ты клиенттің айнымалы шығыннан кейінгі жинақталған үлесімен салыстырыңыз.",
        "Contribution per order = order revenue − its variable costs. With positive contribution, break-even orders = fixed costs for the period ÷ contribution per order, rounded up. CAC = acquisition spend ÷ new customers for a matching period. For CAC payback, compare acquisition cost with cumulative customer contribution after variable costs.",
    ),
    "operations": (
        "Доля доставок вовремя = заказы с доставкой к обещанному сроку ÷ заказы, чей обещанный срок уже наступил. Включите в знаменатель просроченные недоставленные заказы и заранее определите правила для отмен. Разложите задержку на комплектацию, отгрузку и путь перевозчика. Для возвратов считайте отдельную долю по доставленным заказам с одинаковым сроком наблюдения.",
        "Уақтылы жеткізу үлесі = уәде етілген мерзімге дейін жеткізілген тапсырыс ÷ уәде етілген мерзімі келген тапсырыс. Мерзімі өткен жеткізілмеген тапсырыстарды бөлімге қосып, жойылған тапсырыстарға ереже белгілеңіз. Кідірісті жинау, жөнелту және тасымалдау кезеңдеріне бөліңіз. Қайтарым үлесін бақылау мерзімі бірдей жеткізілген тапсырыстар бойынша бөлек есептеңіз.",
        "On-time delivery rate = orders delivered by the promise ÷ orders whose promised deadline has passed. Include overdue undelivered orders in the denominator and document how cancellations are handled. Split delays into picking, dispatch and transit. Measure returns separately among delivered orders with the same observation window.",
    ),
    "clarify": (
        "Какое решение вы хотите принять и какой показатель вас интересует? Можно спросить про выручку, маржу, средний чек, конверсию, ROAS или качество данных.",
        "Қандай шешім қабылдағыңыз келеді және сізді қай көрсеткіш қызықтырады? Түсім, маржа, орташа чек, конверсия, ROAS немесе дерек сапасы туралы сұраңыз.",
        "What decision are you making and which metric matters? You can ask about revenue, margin, average order value, conversion, ROAS or data quality.",
    ),
}

DETAILED_TOPICS = frozenset({"retention", "inventory", "plan", "experiment", "unit_economics", "operations"})

DATA_REQUEST = (
    "Для вашего расчёта приложите CSV и укажите нужный период. Формат можно взять из example.csv.",
    "Есептеу үшін CSV тіркеп, қажетті кезеңді көрсетіңіз. Пішім үлгісі example.csv файлында бар.",
    "To calculate your figures, attach a CSV and specify the period. See example.csv for the format.",
)

TOPIC_NAMES = {
    "profit": ("Прибыль и маржа", "Пайда және маржа", "Profit and margin"),
    "sales": ("Продажи и средний чек", "Сатылым және орташа чек", "Sales and order value"),
    "conversion": ("Конверсия и воронка", "Конверсия және сату воронкасы", "Conversion and funnel"),
    "marketing": ("Эффективность рекламы", "Жарнама тиімділігі", "Ad performance"),
    "quality": ("Качество данных", "Дерек сапасы", "Data quality"),
    "report": ("Отчёт для руководителя", "Басшыға арналған есеп", "Management report"),
    "periods": ("Сравнение периодов", "Кезеңдерді салыстыру", "Period comparison"),
    "retention": ("Удержание и отток клиентов", "Клиенттердің сақталуы және кетуі", "Retention and churn"),
    "inventory": ("Запасы и оборачиваемость", "Тауар қоры және айналым", "Inventory and turnover"),
    "plan": ("План-факт и бюджет", "Жоспар-факт және бюджет", "Plan versus actual"),
    "experiment": ("A/B-тесты", "A/B сынақтары", "A/B experiments"),
    "unit_economics": ("Юнит-экономика", "Юнит-экономика", "Unit economics"),
    "operations": ("Доставка и операции", "Жеткізу және операциялар", "Delivery and operations"),
}

EVIDENCE = {
    "profit": ("выручка и затраты по товарам и периодам", "тауарлар мен кезеңдер бойынша түсім мен шығын", "revenue and costs by product and period"),
    "sales": ("выручка и число заказов по товарам или каналам", "тауарлар немесе арналар бойынша түсім мен тапсырыс саны", "revenue and order counts by product or channel"),
    "conversion": ("число пользователей на каждом этапе от визита до целевого действия", "кіруден мақсатты әрекетке дейінгі әр қадамдағы пайдаланушылар саны", "user counts at each step from visit to target action"),
    "marketing": ("расходы и отнесённая к рекламе выручка по кампаниям", "науқандар бойынша жарнама шығыны мен оған жатқызылған түсім", "spend and attributed revenue by campaign"),
    "quality": ("выгрузка, ключ операции и контрольная сумма из источника", "дерек файлы, операция кілті және дереккөздегі бақылау сомасы", "the export, a transaction key and the source total"),
    "report": ("решение, которое должен принять руководитель, период и целевые KPI", "басшының қабылдайтын шешімі, кезең және мақсатты KPI", "the decision, reporting window and target KPIs"),
    "periods": ("даты начала и конца обоих периодов и дни, охваченные данными", "екі кезеңнің басталу және аяқталу күндері, дерек қамтитын күндер", "both date ranges and the days covered by the data"),
    "retention": ("обезличенный идентификатор клиента, дата первого события и даты последующей активности или отмены", "клиенттің бүркеншік идентификаторы, алғашқы оқиға күні және кейінгі белсенділік немесе бас тарту күндері", "pseudonymous customer ID, first event date, and later activity or cancellation dates"),
    "inventory": ("SKU, склад, ежедневные остатки и продажи, даты отсутствия товара и сроки поставки", "SKU, қойма, күндік қор мен сату, тауар болмаған күндер және жеткізу мерзімі", "SKU, warehouse, daily stock and sales, stockout dates and supplier lead times"),
    "plan": ("утверждённый план и факт по одному периоду, подразделению, единице измерения и статье", "бір кезең, бөлім, өлшем бірлігі және бап бойынша бекітілген жоспар мен нақты дерек", "approved plan and actuals for the same period, department, unit and line item"),
    "experiment": ("единица случайного распределения, вариант, экспозиция, события, основная метрика и правило остановки", "кездейсоқ бөлу бірлігі, нұсқа, көрсетілім, оқиғалар, негізгі көрсеткіш және тоқтату ережесі", "randomization unit, variant, exposure and outcomes, primary metric and stopping rule"),
    "unit_economics": ("выручка и переменные затраты на заказ, постоянные затраты периода, расходы на привлечение и число новых клиентов", "тапсырыс түсімі мен айнымалы шығыны, кезеңнің тұрақты шығыны, тарту шығыны және жаңа клиент саны", "order revenue and variable costs, period fixed costs, acquisition spend and new customer counts"),
    "operations": ("обезличенный идентификатор заказа, обещанный срок, время сборки, отгрузки и доставки, статус и причина отмены или возврата", "тапсырыстың бүркеншік идентификаторы, уәде етілген мерзім, жинау, жөнелту және жеткізу уақыты, күйі және жою не қайтару себебі", "pseudonymous order ID, promised date, picking, dispatch and delivery timestamps, status and reason for cancellation or return"),
}
EVIDENCE_TITLE = ("Что нужно для проверки", "Тексеру үшін не қажет", "What to provide")


def explain(topics: tuple[str, ...], language_index: int) -> str:
    if not topics:
        return "\n\n".join((GUIDE["clarify"][language_index], DATA_REQUEST[language_index]))
    sections = []
    inputs = []
    for topic in topics:
        heading = TOPIC_NAMES[topic][language_index]
        sections.append(heading + "\n" + GUIDE[topic][language_index])
        inputs.append("• " + EVIDENCE[topic][language_index])
    sections.append(EVIDENCE_TITLE[language_index] + "\n" + "\n".join(inputs))
    return "\n\n".join(sections)
