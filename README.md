## Chatbot - Backend Teknik Dokumantasyonu

### Mimari Genel Bakis

- **Framework**: FastAPI (async)
- **Veritabani**: PostgreSQL + SQLAlchemy async engine
- **Vektor Store**: Chroma (profil bazli koleksiyonlar)
- **LLM Saglayicisi**: OpenAI (LangChain ChatOpenAI)
- **Katmanlar**:
  - `app/api/routes`: HTTP endpointleri
  - `app/services`: is akislari, RAG, bellek, baslik ve arac koordinasyonu
  - `app/repositories`: SQLAlchemy ile DB erisimi
  - `app/core`: konfig, lifecycle, tenant/profil tanimlari
  - `app/adapters`: LLM ve vector store adaptorleri
  - `app/models`: Pydantic schemalari ve ORM modelleri

### Coklu Tenant / Profil Konfigurasyonu

Profil davranislarini `tenant-config.json` dosyasi uzerinden yonetebilirsiniz (ornegi `tenant-config.example.json`). Her profil icin:
- `vector_collection`: Chroma koleksiyon adi (`tenant_profile`).
- `source_paths`: Ilgili PDF yollarinin listesi.
- `tools`: Tool calling icin etkin arac listesi.
- `prompt_template` / `summary_context`: Opsiyonel ozel prompt ayarlari.

`TENANT_CONFIG_PATH` degiskeni verilmezse uygulama `ALLOWED_ROLES` ve `DEFAULT_SOURCES` degerlerinden tek bir tenant/profil fallback'i olusturur.

### Baslangic Akisi (`app/core/lifespan.py`)

1. SQLAlchemy motoru ve session factory yaratilir.
2. Tenant/profil konfig dosyasi okunur (yoksa fallback).
3. `INIT_VECTOR_ON_STARTUP=true` ise her profilin `source_paths` listesi icin Chroma koleksiyonlari yeniden olusturulur.
4. Varlik durumuna gore ilk koleksiyon yuku `app.state.vectorstore` altinda tutulur.
5. `INIT_LLM_ON_STARTUP=true` ise tek defalik LLM client'i hazirlanir.

### Tool Calling Altyapisi

`app/services/tool_service.py` basit bir arayuz saglar.
- Varsayilan olarak `current_datetime` araci bulunur.
- Yeni arac eklemek icin `BaseTool` sinifini miraslayip `ToolManager` registry'sine eklemeniz yeterli.
- Profilde listedigi araclar `RagService` tarafindan otomatik olarak OpenAI function calling formatinda LLM'e tanitilir.

### API Uclari

| Method | Path | Aciklama |
| --- | --- | --- |
| GET | `/health` | DB saglik kontrolu |
| POST | `/chat/{profile_key}` | Sohbet (body: `ChatRequest`) |
| GET | `/chat/{profile_key}/messages` | Profil bazli mesaj listesi |
| GET | `/chat/{profile_key}/sessions` | Profil bazli oturum listesi |
| POST | `/chat/{profile_key}/sessions/{session_id}/title` | Baslik guncelle |
| DELETE | `/chat/{profile_key}/sessions/{session_id}` | Oturum sil |
| POST | `/chat/{profile_key}/feedback` | Mesaj geri bildirimi |

`ChatRequest` ornegi (profil path parametresi ile):
```
POST /chat/ogrenci
Headers: x-tenant-id: pilot
{
  "question": "Ogrenci paneline nasil girerim?",
  "user_id": "user-123",
  "tenant_id": "pilot"
}
```

### Docker Compose

`docker-compose.yml` ortam degiskenleri:
- `TENANT_CONFIG_FILE`: Hosttaki konfigurasyon dosya yolu (varsayilan `./tenant-config.json`).
- `TENANT_CONFIG_PATH`: Konteyner icinde dosyanin okunacagi yol (`/app/tenant-config.json`).
- `DEFAULT_TENANT_ID`, `DEFAULT_SOURCES`: Fallback icin varsayilan degerler.

Compose calistirmadan once `tenant-config.json` olusturun veya `tenant-config.example.json` dosyasini kopyalayip guncelleyin.

### Vektor Yonetimi

- Startup otomatik ingest istemiyorsaniz `INIT_VECTOR_ON_STARTUP=false` veya ilgili profilin `source_paths` listesini bos birakin.
- Manuel ingest icin `build_or_refresh_index(...)` fonksiyonunu uygun parametrelerle calistirabilirsiniz.

### Calistirma

```bash
docker compose up --build
```
veya yerelde:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Diger Notlar

- `init-scripts/init.sql` migrasyonu mevcut tabloları yeni tenant/profil modeline göre gunceller.
- Tool calling su an baslangic seviyesindedir; profil config'ine eklediginiz araclari `ToolManager`’da tanimli hale getirmelisiniz.
- Chroma icin uzun vadede `langchain_openai` ve `langchain_chroma` paketlerine gecis onerilir (su an icin community modulleri kullaniliyor).
### Detayli Islem Akisi

1. **Uygulama Baslangici**  
   - `app/main.py` FastAPI uygulamasini olusturur ve `lifespan` fonksiyonunu baglar.  
   - `app/core/lifespan.py` calisir: SQLAlchemy motoru kurulur, tenant/profil konfig dosyasi okunur, rate limiter hazirlanir.  
   - `INIT_VECTOR_ON_STARTUP=true` ise `tenant-config.json` icindeki her profil icin `source_paths` taranir, PDF dokumanlari `build_or_refresh_index` ile ilgili `vector_collection` adiyla Chroma'ya yazilir.  
   - Ilk koleksiyon handle'i `app.state.vectorstore` olarak saklanir, gerekirse LLM once yuklenir (`app.state.llm`).

2. **HTTP Katmani**  
   - `POST /chat/{profile_key}` (`app/api/routes/chat.py`): `x-tenant-id` basligindan tenant, path'ten profil okunur. `TenantConfigRegistry` uzerinden profil konfigi bulunmazsa 404 doner.  
   - `ChatService` olusturulur ve `handle_chat` cagrilir.

3. **ChatService Islemleri** (`app/services/chat_service.py`)  
   - Girdiler `sanitize_identifier` ve `ensure_safe_prompt` ile temizlenir.  
   - Rate limiter anahtari `tenant_id:profile_key:user_id:IP` olarak calisir.  
   - `SessionRepo.ensure_session` profil/tenant bazli `chat_sessions` kaydini olusturur/gunceller.  
   - `ChatRepo.insert_message` kullanici mesajini `chat_messages` tablosuna yazar (tenant ve profil kolonlari dahil).  
   - `MemoryService.build_memory` profil ozetini hazirlar, `RagService.answer` soruya yanit uretir, `ChatRepo.insert_message` ve `ChatRepo.insert_history` asistan yanitini ve audit kaydini saklar.  
   - `TitleService.maybe_set_session_title` basligi gerekirse gunceller, sonuc `ChatResponse` olarak dondurulur.

4. **RAG ve Tool Calling** (`app/services/rag_service.py`)  
   - Profil konfiginden `vector_collection` cekilir, ilgili Chroma koleksiyonu acilir.  
   - `retrieve_context` chunk metadata'sini `{"$and": [{"profile_key": {"$eq": ...}}, {"tenant_id": {"$eq": ...}}]}` filtresiyle sorgular.  
   - Profil prompt sablonu kullanilarak LLM'e girdi verilir. Profilde tool tanimliysa `ToolManager` fonksiyon spesifikasyonlarini LLM'e gecirir, tool cagrilari calistirilir ve final cevap uretilir.

5. **Veritabani Modeli** (`app/models/db_models.py`)  
   - Tablolarin tamami `tenant_id` ve `profile_key` kolonlari icerir.  
   - `init-scripts/init.sql` bu kolonlari ekler/migrasyon yapar, gerekli indexleri olusturur.

6. **Profil ve Dokuman Izolasyonu**  
   - `tenant-config.json` her profil icin ayri `vector_collection` ve `source_paths` tanimlar.  
   - PDF chunk'lari metadata olarak `tenant_id` ve `profile_key` tasir, Chroma sorgulari sadece ilgili profil/tenant verisini dondurur.  
   - `get_collections.py` ile koleksiyon adlari ve `peek` ciktilari incelenerek dogrulanabilir.

7. **Docker Calistirma**  
   - `docker-compose.yml` Postgres + uygulama konteynerini ayaga kaldirir, `tenant-config.json` dosyasini read-only volume olarak iceri baglar.  
   - Ilk calistirmada init script tabloyu hazirlar, sonraki calistirmalarda configurasyon degistiginde koleksiyonlar tekrar olusturulur.

Bu akista her istek belirli tenant ve profil baglaminda tutulur, dokumanlar karismaz, tool calling opsiyonel olarak profil konfigurasyonundan yönetilir.
