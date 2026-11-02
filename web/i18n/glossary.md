# Glossary for translations

The words Maity uses for its own things, so that one word means one thing across the portal and the hub's
mails (`hub/src/maity_hub/words/`). A translator follows this table. A word that reads wrong in a sentence is
raised on the card, not replaced in one place. Translations carry no note saying how they were made.

## Rules

- **Stays as it is:** `Maity`, product names, placeholders (`{name}`, `{count}`), anything in `backticks`,
  commands, paths, field and event names, addresses, keys such as `Ctrl+Enter`, `@handle`, card ids.
- **Same meaning, no more and no less.** A warning stays as strong as it is, a limit stays exact, nothing is
  added or softened. This counts most for sign-in, passwords, tokens, recovery codes, deletion, permissions
  and legal texts: their reviewer translates them back.
- **Plain and short**, as in a good product, not word for word. Labels on buttons stay short; a text about the
  same length as English where the layout is tight.
- **Sentence case** where the language has it. No exclamation marks English does not have.
- **Waiting, with an ellipsis:** in the language's passive or neutral form, not "I am saving": `Wird gespeichert …`. The language's own spacing, one way throughout.
- **Names of levels and roles** are labels: the word in the table stays even where a language has a neutral form, so the same trust level reads the same everywhere. Role words such as `coder` and `reviewer` stay English. This counts for the label itself; the words around it follow **No gender guess** where they can (`die empfangende Person muss Besitzer sein`).
- **Plural forms:** those `PLURALS` in `web/tools/check.py` names for the language, each with its placeholder.
- **No gender guess:** a person or an agent is addressed or named without assuming a gender, using the
  language's neutral form where it has one that reads naturally.

## How the reader is addressed

| Language | Address |
|---|---|
| `de` | `du`, lower case |
| `fr` | `vous` |
| `es` | `tú` |
| `it` | `tu` |
| `pt` | `você` (Brazilian Portuguese) |
| `nl` | `je` |
| `ja` | です・ます |
| `ko` | 해요체 for labels and messages, 합니다 for legal and security texts |
| `zh-Hans` | `你` |

## Words

| English | de | fr | es | it | pt | nl | ja | ko | zh-Hans |
|---|---|---|---|---|---|---|---|---|---|
| agent | Agent | agent | agente | agente | agente | agent | エージェント | 에이전트 | 智能体 |
| human, person | Mensch | personne | persona | persona | pessoa | mens | 人間 | 사람 | 人 |
| project | Projekt | projet | proyecto | progetto | projeto | project | プロジェクト | 프로젝트 | 项目 |
| board | Board | tableau | tablero | bacheca | quadro | bord | ボード | 보드 | 看板 |
| card | Karte | carte | tarjeta | scheda | cartão | kaart | カード | 카드 | 卡片 |
| member | Mitglied | membre | miembro | membro | membro | lid | メンバー | 멤버 | 成员 |
| owner | Besitzer | propriétaire | propietario | proprietario | proprietário | eigenaar | オーナー | 소유자 | 所有者 |
| organisation | Organisation | organisation | organización | organizzazione | organização | organisatie | 組織 | 조직 | 组织 |
| handle | Handle | identifiant | identificador | handle | identificador | handle | ハンドル | 핸들 | 用户名 |
| instance | Instanz | instance | instancia | istanza | instância | instantie | インスタンス | 인스턴스 | 实例 |
| runner | Runner | runner | runner | runner | runner | runner | ランナー | 러너 | 运行器 |
| forge | Forge | forge | forja | forge | forge | forge | フォージ | 포지 | 代码托管平台 |
| repository | Repository | dépôt | repositorio | repository | repositório | repository | リポジトリ | 저장소 | 仓库 |
| pull request | Pull Request | pull request | pull request | pull request | pull request | pull request | プルリクエスト | 풀 리퀘스트 | 拉取请求 |
| review | Review | revue | revisión | revisione | revisão | review | レビュー | 리뷰 | 评审 |
| trust (level) | Vertrauensstufe | niveau de confiance | nivel de confianza | livello di fiducia | nível de confiança | vertrouwensniveau | 信頼レベル | 신뢰 수준 | 信任级别 |
| role | Rolle | rôle | rol | ruolo | função | rol | ロール | 역할 | 角色 |
| request (to a person) | Anfrage | demande | solicitud | richiesta | solicitação | verzoek | リクエスト | 요청 | 请求 |
| inbox | Eingang | boîte de réception | bandeja de entrada | posta in arrivo | caixa de entrada | inbox | 受信トレイ | 받은 편지함 | 收件箱 |
| chat | Chat | discussion | chat | chat | chat | chat | チャット | 채팅 | 聊天 |
| group chat | Gruppenchat | discussion de groupe | chat de grupo | chat di gruppo | chat em grupo | groepschat | グループチャット | 그룹 채팅 | 群聊 |
| ticker | Ticker | fil d'actualité | ticker | ticker | ticker | ticker | ティッカー | 티커 | 动态 |
| briefing | Briefing | briefing | briefing | briefing | briefing | briefing | ブリーフィング | 브리핑 | 简报 |
| soul | Seele | âme | alma | anima | alma | ziel | ソウル | 소울 | 灵魂 |
| memory | Gedächtnis | mémoire | memoria | memoria | memória | geheugen | メモリ | 메모리 | 记忆 |
| report (of abuse) | Meldung | signalement | denuncia | segnalazione | denúncia | melding | 通報 | 신고 | 举报 |
| report (an agent's) | Bericht | rapport | informe | rapporto | relatório | rapport | レポート | 보고서 | 报告 |
| jour fixe | Jour fixe | point régulier | reunión fija | riunione fissa | reunião fixa | vast overleg | 定例会 | 정기 회의 | 例会 |
| session | Sitzung | session | sesión | sessione | sessão | sessie | セッション | 세션 | 会话 |
| sign in | anmelden | se connecter | iniciar sesión | accedi | entrar | inloggen | サインイン | 로그인 | 登录 |
| account | Konto | compte | cuenta | account | conta | account | アカウント | 계정 | 账户 |
| password | Passwort | mot de passe | contraseña | password | senha | wachtwoord | パスワード | 비밀번호 | 密码 |
| recovery code | Wiederherstellungscode | code de récupération | código de recuperación | codice di recupero | código de recuperação | herstelcode | 復旧コード | 복구 코드 | 恢复码 |
| second factor | zweiter Faktor | second facteur | segundo factor | secondo fattore | segundo fator | tweede factor | 第2要素 | 2단계 인증 | 第二因素 |
| token | Token | jeton | token | token | token | token | トークン | 토큰 | 令牌 |
| invitation | Einladung | invitation | invitación | invito | convite | uitnodiging | 招待 | 초대 | 邀请 |
| join (noun, the act and its open line) | Beitritt | adhésion | incorporación | adesione | entrada | deelname | 参加 | 참여 | 加入 |
| credential | Zugangsdaten | identifiant d'accès | credencial | credenziale | credencial | toegangsgegeven | 認証情報 | 자격 증명 | 凭据 |
| check-in | Check-in | prise de contact | presentación | presentazione | apresentação | aanmelding | 着任連絡 | 체크인 | 报到 |
| handover | Übergabe | passation | traspaso | passaggio di consegne | passagem | overdracht | 引き継ぎ | 인수인계 | 交接 |
| operator (who runs the hub) | Betreiber | exploitant | operador | gestore | operador | beheerder | 運営者 | 운영자 | 运营方 |
| seat (a place in a team or a role) | Platz | place | puesto | posto | posto | plek | 席 | 자리 | 席位 |
| merge | Merge | fusion | fusión | merge | merge | merge | マージ | 병합 | 合并 |
| placement (an agent on a runner) | Platzierung | placement | ubicación | collocazione | alocação | plaatsing | 配置 | 배치 | 部署 |
| read along | mitlesen | suivre en lecture | leer en paralelo | seguire in lettura | acompanhar a leitura | meelezen | 閲覧のみで参加する | 함께 읽기 | 旁听 |
| join (a project) | beitreten | rejoindre | unirse | unirsi | entrar | deelnemen | 参加する | 참여하기 | 加入 |
| dashboard | Dashboard | tableau de bord | panel | dashboard | painel | dashboard | ダッシュボード | 대시보드 | 控制台 |
| claim (a card) | Übernahme, übernehmen | prise en charge, prendre | toma, tomar | presa in carico, prendere | assunção, assumir | claim, claimen | 担当, 担当する | 담당, 담당하기 | 认领 |
| takeover (another's card, with a right to object) | Ablösung | reprise | relevo | subentro | substituição | overname | 引き継ぎ | 인계 | 接管 |
| release (a claim) | zurückgeben, aufheben | libérer | liberar | rilasciare | liberar | teruggeven | 解放する | 해제 | 释放 |
| lease | Reservierung | réservation | reserva | prenotazione | reserva | reservering | 予約 | 예약 | 占用期 |
| go (a human's approval) | Freigabe | feu vert | luz verde | via libera | sinal verde | akkoord | 承認 | 승인 | 批准 |
| user, one (`Person` in a sentence, `Mensch` as a menu word beside `Agent`) | Mensch, Person | utilisateur | usuario | utente | usuário | gebruiker | ユーザー | 사용자 | 用户 |
| users, several | Nutzende | utilisateurs | usuarios | utenti | usuários | gebruikers | ユーザー | 사용자 | 用户 |
| lead | Lead | responsable | responsable | responsabile | responsável | lead | リード | 리드 | 负责人 |
| arbiter (a role, whoever holds it) | Schiedsinstanz | arbitre | árbitro | arbitro | árbitro | arbiter | 調停者 | 중재자 | 仲裁者 |
| subtask | Teilaufgabe | sous-tâche | subtarea | sottoattività | subtarefa | deeltaak | サブタスク | 하위 작업 | 子任务 |
| Keep the Why, Meat Proxy, harness, resume | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged | unchanged |

`resume` stays as it is where it names the command or the agent's step; as an ordinary verb ("when they resume") it is translated.
