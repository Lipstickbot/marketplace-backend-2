-- Three local mock demos and nine clearly marked future cards.
-- Uses engine metadata from upstream 0224719c29cc47cde7607a376c8b511a1ee05da2.
begin;
insert into public.agents(slug,name,description,category,status,engine_slug,version,supported_languages,
  capabilities,accepted_file_purposes,input_schema,output_schema)
select slug,name,description,category,status,engine_slug,version,supported_languages,
  capabilities,accepted_file_purposes,input_schema,output_schema
from jsonb_to_recordset($catalog$[
  {
    "slug": "marketing",
    "category": "marketing",
    "version": "1.0.0",
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [
      "audience_analysis",
      "marketing_strategy",
      "ad_copy",
      "content_plan",
      "social_posts",
      "commercial_offer",
      "email_campaign",
      "smb_recommendations"
    ],
    "accepted_file_purposes": [
      "brief",
      "knowledge_base"
    ],
    "input_schema": {
      "$defs": {
        "HistoryMessage": {
          "properties": {
            "role": {
              "enum": [
                "user",
                "assistant"
              ],
              "title": "Role",
              "type": "string"
            },
            "content": {
              "maxLength": 4000,
              "minLength": 1,
              "title": "Content",
              "type": "string"
            }
          },
          "required": [
            "role",
            "content"
          ],
          "title": "HistoryMessage",
          "type": "object"
        }
      },
      "additionalProperties": false,
      "description": "Body of ``POST /agents/{slug}/run``. User and company come from authentication.",
      "examples": [
        {
          "file_ids": [],
          "language": "ru",
          "message": "Создай контент-план для кофейни в Алматы"
        }
      ],
      "properties": {
        "message": {
          "description": "User request to the agent",
          "maxLength": 20000,
          "minLength": 1,
          "title": "Message",
          "type": "string"
        },
        "language": {
          "anyOf": [
            {
              "enum": [
                "ru",
                "kk",
                "en"
              ],
              "type": "string"
            },
            {
              "const": "auto",
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "ru | kk | en. Omit or 'auto' to detect from the message.",
          "title": "Language"
        },
        "file_ids": {
          "description": "Platform file UUIDs from POST /files/upload; Backend 2 maps them to engine IDs.",
          "items": {
            "type": "string"
          },
          "maxItems": 10,
          "title": "File Ids",
          "type": "array"
        },
        "options": {
          "properties": {
            "task": {
              "default": "auto",
              "description": "Marketing task; 'auto' detects it from the message",
              "enum": [
                "auto",
                "audience_analysis",
                "marketing_strategy",
                "ad_copy",
                "content_plan",
                "social_posts",
                "commercial_offer",
                "email_campaign",
                "smb_recommendations"
              ],
              "title": "Task",
              "type": "string"
            },
            "business_name": {
              "anyOf": [
                {
                  "maxLength": 200,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Business Name"
            },
            "industry": {
              "anyOf": [
                {
                  "maxLength": 200,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Industry"
            },
            "city": {
              "anyOf": [
                {
                  "maxLength": 100,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "City"
            },
            "target_audience": {
              "anyOf": [
                {
                  "maxLength": 1000,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Target Audience"
            },
            "platforms": {
              "items": {
                "enum": [
                  "instagram",
                  "tiktok",
                  "telegram"
                ],
                "type": "string"
              },
              "maxItems": 3,
              "title": "Platforms",
              "type": "array"
            },
            "tone": {
              "anyOf": [
                {
                  "maxLength": 200,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Tone"
            },
            "budget_kzt": {
              "anyOf": [
                {
                  "maximum": 10000000000,
                  "minimum": 0,
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Budget in tenge",
              "title": "Budget Kzt"
            },
            "period_days": {
              "anyOf": [
                {
                  "maximum": 365,
                  "minimum": 1,
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Period Days"
            }
          },
          "title": "MarketingOptions",
          "type": "object"
        },
        "history": {
          "description": "Optional previous turns of this chat (untrusted)",
          "items": {
            "$ref": "#/$defs/HistoryMessage"
          },
          "maxItems": 10,
          "title": "History",
          "type": "array"
        }
      },
      "required": [
        "message"
      ],
      "title": "marketing_run_request",
      "type": "object"
    },
    "output_schema": {
      "properties": {
        "task": {
          "title": "Task",
          "type": "string"
        },
        "platforms": {
          "items": {
            "type": "string"
          },
          "title": "Platforms",
          "type": "array"
        },
        "draft": {
          "default": true,
          "title": "Draft",
          "type": "boolean"
        },
        "published": {
          "default": false,
          "title": "Published",
          "type": "boolean"
        },
        "contains_numbers_to_verify": {
          "title": "Contains Numbers To Verify",
          "type": "boolean"
        }
      },
      "required": [
        "task",
        "platforms",
        "contains_numbers_to_verify"
      ],
      "title": "MarketingOutput",
      "type": "object"
    },
    "name": "AI Marketing — демо",
    "description": "Черновики постов, контент-планы и маркетинговые идеи. Локальное демо работает в mock-режиме: ответы демонстрационные, не результат реальной модели.",
    "status": "published",
    "engine_slug": "marketing"
  },
  {
    "slug": "support",
    "category": "customer_support",
    "version": "1.0.0",
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [
      "knowledge_base_qa",
      "faq",
      "complaint_handling",
      "source_citation",
      "escalation_detection",
      "manager_handoff_draft"
    ],
    "accepted_file_purposes": [
      "knowledge_base"
    ],
    "input_schema": {
      "$defs": {
        "HistoryMessage": {
          "properties": {
            "role": {
              "enum": [
                "user",
                "assistant"
              ],
              "title": "Role",
              "type": "string"
            },
            "content": {
              "maxLength": 4000,
              "minLength": 1,
              "title": "Content",
              "type": "string"
            }
          },
          "required": [
            "role",
            "content"
          ],
          "title": "HistoryMessage",
          "type": "object"
        }
      },
      "additionalProperties": false,
      "description": "Body of ``POST /agents/{slug}/run``. User and company come from authentication.",
      "examples": [
        {
          "file_ids": [],
          "language": "ru",
          "message": "Создай контент-план для кофейни в Алматы"
        }
      ],
      "properties": {
        "message": {
          "description": "User request to the agent",
          "maxLength": 20000,
          "minLength": 1,
          "title": "Message",
          "type": "string"
        },
        "language": {
          "anyOf": [
            {
              "enum": [
                "ru",
                "kk",
                "en"
              ],
              "type": "string"
            },
            {
              "const": "auto",
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "ru | kk | en. Omit or 'auto' to detect from the message.",
          "title": "Language"
        },
        "file_ids": {
          "description": "Platform file UUIDs from POST /files/upload; Backend 2 maps them to engine IDs.",
          "items": {
            "type": "string"
          },
          "maxItems": 10,
          "title": "File Ids",
          "type": "array"
        },
        "options": {
          "properties": {
            "mode": {
              "default": "auto",
              "description": "Hint about the request type; 'auto' lets the agent classify it",
              "enum": [
                "auto",
                "question",
                "complaint",
                "faq"
              ],
              "title": "Mode",
              "type": "string"
            },
            "top_k": {
              "anyOf": [
                {
                  "maximum": 10,
                  "minimum": 1,
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Number of fragments to retrieve",
              "title": "Top K"
            }
          },
          "title": "SupportOptions",
          "type": "object"
        },
        "history": {
          "description": "Optional previous turns of this chat (untrusted)",
          "items": {
            "$ref": "#/$defs/HistoryMessage"
          },
          "maxItems": 10,
          "title": "History",
          "type": "array"
        }
      },
      "required": [
        "message"
      ],
      "title": "support_run_request",
      "type": "object"
    },
    "output_schema": {
      "$defs": {
        "Handoff": {
          "properties": {
            "summary": {
              "title": "Summary",
              "type": "string"
            },
            "category": {
              "title": "Category",
              "type": "string"
            },
            "priority": {
              "enum": [
                "low",
                "normal",
                "high"
              ],
              "title": "Priority",
              "type": "string"
            },
            "missing_information": {
              "items": {
                "type": "string"
              },
              "title": "Missing Information",
              "type": "array"
            },
            "suggested_next_steps": {
              "items": {
                "type": "string"
              },
              "title": "Suggested Next Steps",
              "type": "array"
            },
            "delivered": {
              "default": false,
              "title": "Delivered",
              "type": "boolean"
            },
            "delivery_note": {
              "title": "Delivery Note",
              "type": "string"
            }
          },
          "required": [
            "summary",
            "category",
            "priority",
            "missing_information",
            "suggested_next_steps",
            "delivery_note"
          ],
          "title": "Handoff",
          "type": "object"
        }
      },
      "properties": {
        "intent": {
          "enum": [
            "question",
            "complaint",
            "faq",
            "other"
          ],
          "title": "Intent",
          "type": "string"
        },
        "answer_status": {
          "enum": [
            "answered",
            "escalation_required"
          ],
          "title": "Answer Status",
          "type": "string"
        },
        "handoff": {
          "anyOf": [
            {
              "$ref": "#/$defs/Handoff"
            },
            {
              "type": "null"
            }
          ]
        },
        "retrieved_fragments": {
          "title": "Retrieved Fragments",
          "type": "integer"
        },
        "neutralized_injection_fragments": {
          "title": "Neutralized Injection Fragments",
          "type": "integer"
        }
      },
      "required": [
        "intent",
        "answer_status",
        "handoff",
        "retrieved_fragments",
        "neutralized_injection_fragments"
      ],
      "title": "SupportOutput",
      "type": "object"
    },
    "name": "AI Support — демо",
    "description": "Ответы по загруженной базе знаний и подготовка обращения менеджеру. Локальное демо работает в mock-режиме; отправки в CRM нет.",
    "status": "published",
    "engine_slug": "support"
  },
  {
    "slug": "hr",
    "category": "hr",
    "version": "1.0.0",
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [
      "resume_summary",
      "experience_extraction",
      "skills_and_education_extraction",
      "job_requirements",
      "requirements_check",
      "interview_questions",
      "job_description"
    ],
    "accepted_file_purposes": [
      "resume",
      "job_description"
    ],
    "input_schema": {
      "$defs": {
        "HistoryMessage": {
          "properties": {
            "role": {
              "enum": [
                "user",
                "assistant"
              ],
              "title": "Role",
              "type": "string"
            },
            "content": {
              "maxLength": 4000,
              "minLength": 1,
              "title": "Content",
              "type": "string"
            }
          },
          "required": [
            "role",
            "content"
          ],
          "title": "HistoryMessage",
          "type": "object"
        }
      },
      "additionalProperties": false,
      "description": "Body of ``POST /agents/{slug}/run``. User and company come from authentication.",
      "examples": [
        {
          "file_ids": [],
          "language": "ru",
          "message": "Создай контент-план для кофейни в Алматы"
        }
      ],
      "properties": {
        "message": {
          "description": "User request to the agent",
          "maxLength": 20000,
          "minLength": 1,
          "title": "Message",
          "type": "string"
        },
        "language": {
          "anyOf": [
            {
              "enum": [
                "ru",
                "kk",
                "en"
              ],
              "type": "string"
            },
            {
              "const": "auto",
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "description": "ru | kk | en. Omit or 'auto' to detect from the message.",
          "title": "Language"
        },
        "file_ids": {
          "description": "Platform file UUIDs from POST /files/upload; Backend 2 maps them to engine IDs.",
          "items": {
            "type": "string"
          },
          "maxItems": 10,
          "title": "File Ids",
          "type": "array"
        },
        "options": {
          "properties": {
            "task": {
              "default": "auto",
              "description": "HR task; 'auto' detects it from the message and files",
              "enum": [
                "auto",
                "resume_summary",
                "job_requirements",
                "requirements_check",
                "interview_questions",
                "job_description"
              ],
              "title": "Task",
              "type": "string"
            },
            "job_title": {
              "anyOf": [
                {
                  "maxLength": 200,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Job Title"
            },
            "job_description": {
              "anyOf": [
                {
                  "maxLength": 20000,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "description": "Vacancy text (alternative to a job_description file)",
              "title": "Job Description"
            },
            "question_count": {
              "default": 8,
              "maximum": 20,
              "minimum": 3,
              "title": "Question Count",
              "type": "integer"
            }
          },
          "title": "HROptions",
          "type": "object"
        },
        "history": {
          "description": "Optional previous turns of this chat (untrusted)",
          "items": {
            "$ref": "#/$defs/HistoryMessage"
          },
          "maxItems": 10,
          "title": "History",
          "type": "array"
        }
      },
      "required": [
        "message"
      ],
      "title": "hr_run_request",
      "type": "object"
    },
    "output_schema": {
      "properties": {
        "task": {
          "title": "Task",
          "type": "string"
        },
        "result": {
          "additionalProperties": true,
          "title": "Result",
          "type": "object"
        },
        "redactions": {
          "additionalProperties": {
            "type": "integer"
          },
          "title": "Redactions",
          "type": "object"
        },
        "unverified_items": {
          "items": {
            "type": "string"
          },
          "title": "Unverified Items",
          "type": "array"
        },
        "decision_support_only": {
          "default": true,
          "title": "Decision Support Only",
          "type": "boolean"
        }
      },
      "required": [
        "task",
        "result",
        "redactions",
        "unverified_items"
      ],
      "title": "HROutput",
      "type": "object"
    },
    "name": "AI HR — демо",
    "description": "Сводка одного резюме, факты о навыках и вопросы для интервью. Без рейтингов и решений о найме. Локальное демо работает в mock-режиме.",
    "status": "published",
    "engine_slug": "hr"
  },
  {
    "slug": "sales-assistant",
    "name": "Помощник продаж",
    "category": "sales",
    "description": "Подготовка черновиков коммерческих предложений. Скоро; исполнитель ещё не подключён.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "invoice-reader",
    "name": "Разбор счетов",
    "category": "finance",
    "description": "Извлечение реквизитов и сумм для проверки сотрудником. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "meeting-notes",
    "name": "Итоги встреч",
    "category": "productivity",
    "description": "Черновики итогов встреч и списков задач. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "document-translator",
    "name": "Перевод документов",
    "category": "documents",
    "description": "Черновой перевод рабочих документов. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "business-analytics",
    "name": "Бизнес-аналитик",
    "category": "analytics",
    "description": "Объяснение показателей бизнеса и подготовка сводок. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "procurement-assistant",
    "name": "Помощник закупок",
    "category": "operations",
    "description": "Структурирование требований и предложений поставщиков. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "crm-assistant",
    "name": "Помощник CRM",
    "category": "sales",
    "description": "Черновики заметок и последующих действий по сделкам. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "onboarding-assistant",
    "name": "Адаптация сотрудников",
    "category": "hr",
    "description": "Поиск по инструкциям и планы адаптации сотрудников. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  },
  {
    "slug": "inventory-planner",
    "name": "Планирование запасов",
    "category": "operations",
    "description": "Сводки по остаткам и подготовка предложений для проверки менеджером. Скоро.",
    "status": "coming_soon",
    "engine_slug": null,
    "version": null,
    "supported_languages": [
      "ru",
      "kk",
      "en"
    ],
    "capabilities": [],
    "accepted_file_purposes": [],
    "input_schema": {},
    "output_schema": {}
  }
]$catalog$::jsonb) as seed(
  slug text,name text,description text,category text,status public.agent_status,engine_slug text,version text,
  supported_languages text[],capabilities text[],accepted_file_purposes public.file_purpose[],
  input_schema jsonb,output_schema jsonb)
on conflict (slug) do nothing;
commit;
