"""
JWT トークン・パスワードハッシュ・API キーの生成と検証モジュール。

認証の根幹となる暗号処理を一元管理する:
  - パスワード: bcrypt（アダプティブハッシュ、コスト係数で計算時間を調整可能）
  - JWT: HS256 アルゴリズム（HMAC-SHA256）で署名・検証
  - API キー: CSPRNG（暗号学的疑似乱数）で生成、SHA-256 で DB 保存

各関数は独立して単体テスト可能なように副作用を最小限に設計している。
"""

import hashlib
import secrets  # 暗号学的に安全な乱数生成モジュール（random モジュールではない）
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from src.config import settings

# API キーのプレフィックス。"fx_" を付与することで:
# 1. 誤ってコードに貼り付けた場合に検索・検出しやすい
# 2. GitGuardian 等のシークレットスキャナーがこのパターンを検知できる
# 3. resolve_api_key で簡易的な事前フィルタリングに使用
API_KEY_PREFIX = "fx_"


def hash_password(password: str) -> str:
    """
    パスワードを bcrypt でハッシュ化して返す。

    bcrypt はアダプティブハッシュ関数で、コスト係数（デフォルト 12）により
    意図的に計算を遅くすることでブルートフォース攻撃を困難にする。

    bcrypt の 72 バイト制限について:
      bcrypt は内部的に入力を 72 バイトで切り詰める仕様のため、
      72 バイト以上のパスワードは同一ハッシュになる可能性がある（脆弱性）。
      ここでは [:72] で明示的に切り詰めてこの挙動を明確にしている。

    Args:
        password: ハッシュ化する生のパスワード文字列。

    Returns:
        str: bcrypt ハッシュ文字列（例: "$2b$12$..."）。
             データベースに安全に保存できる形式。
    """
    # UTF-8 エンコード後、bcrypt の 72 バイト制限に合わせて切り詰める
    pwd_bytes = password.encode("utf-8")[:72]
    # bcrypt.gensalt() はランダムなソルトを生成（レインボーテーブル攻撃対策）
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    平文パスワードと bcrypt ハッシュを比較して一致を検証する。

    bcrypt.checkpw は定数時間比較を使用しているため、
    タイミング攻撃（timing attack）に対して安全。

    Args:
        plain: ユーザーが入力した平文パスワード。
        hashed: データベースに保存されている bcrypt ハッシュ。

    Returns:
        bool: パスワードが一致すれば True、不一致または入力エラーは False。
    """
    try:
        # checkpw は内部で定数時間比較を行いタイミング攻撃を防ぐ
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # 不正な入力（空文字列・None 等）は False として扱う（例外を上位に伝播させない）
        return False


def create_access_token(user_id: int, tenant_id: int, email: str, role: str) -> str:
    """
    JWT アクセストークンを生成して返す。

    JWT（JSON Web Token）は 3 部構成（ヘッダー.ペイロード.署名）で、
    署名により改ざんを検知できるステートレスな認証トークン。
    有効期限は設定ファイルの jwt_expire_hours で制御する（デフォルト 24 時間）。

    JWT ペイロードに含まれるクレーム:
      - sub: ユーザー ID（JWT 標準の "subject" クレーム）
      - tenant_id: テナント ID（マルチテナント識別用）
      - email: メールアドレス（表示・Stripe プリフィル用）
      - role: ユーザーロール（オーナー判定用）
      - exp: 有効期限（Unix タイムスタンプ秒）
      - iat: 発行日時（Unix タイムスタンプ秒）

    Args:
        user_id: JWT の subject（ユーザー ID）。
        tenant_id: テナント ID（マルチテナント識別）。
        email: ユーザーのメールアドレス。
        role: ユーザーロール（"owner" 等）。

    Returns:
        str: 署名済み JWT トークン文字列（"eyJ..." 形式）。
    """
    now = datetime.now(timezone.utc)
    # 有効期限 = 現在時刻 + 設定値（時間）。timedelta で計算。
    expire = now + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": str(user_id),           # JWT 標準クレーム: subject（ユーザー ID）
        "tenant_id": tenant_id,         # カスタムクレーム: テナント ID
        "email": email,                 # カスタムクレーム: メールアドレス
        "role": role,                   # カスタムクレーム: ロール
        "exp": int(expire.timestamp()),  # JWT 標準クレーム: 有効期限（秒単位 Unix 時刻）
        "iat": int(now.timestamp()),     # JWT 標準クレーム: 発行日時（秒単位 Unix 時刻）
    }
    # HS256（HMAC-SHA256）で署名。jwt_secret は必ず十分な長さのランダム文字列を使用すること。
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    # PyJWT のバージョンにより str または bytes が返るため、str に統一する
    return token if isinstance(token, str) else token.decode("utf-8")


def decode_access_token(token: str) -> dict | None:
    """
    JWT アクセストークンを検証して、ペイロード辞書を返す。

    以下のいずれかの場合に None を返す（例外は内部でキャッチ）:
      - 署名が不正（改ざん）
      - 有効期限切れ（exp クレーム）
      - アルゴリズムが不一致
      - その他の JWT 形式エラー

    Args:
        token: 検証する JWT トークン文字列。

    Returns:
        dict: 有効な JWT のペイロード辞書（クレーム含む）。
              無効・期限切れ・改ざんの場合は None。
    """
    try:
        # algorithms パラメーターはリスト形式で渡す（アルゴリズム混在攻撃を防ぐ）
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        # 期限切れ・署名エラー・形式エラー等すべての JWT エラーを None で返す
        return None


def generate_api_key() -> str:
    """
    暗号学的に安全なランダム API キーを生成する。

    secrets.token_urlsafe は os.urandom を使用した CSPRNG（暗号学的疑似乱数生成器）
    で生成するため、予測不能性が保証される（Python の random モジュールは使用しない）。

    生成されるキーの形式: "fx_" + URL-safe Base64（32 バイト = 43 文字）
    合計長: 46 文字程度。エントロピー: 256 ビット（32 バイト * 8）。

    Returns:
        str: "fx_" プレフィックス付きの API キー文字列（例: "fx_AbCdEfGh..."）。
    """
    # secrets.token_urlsafe(32): 32 バイトのランダムデータを URL-safe Base64 でエンコード
    # 結果は約 43 文字の英数字・記号（-_）のみで構成される安全な文字列
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """
    生の API キーを SHA-256 でハッシュ化して、DB 保存用のハッシュ値を返す。

    API キーはパスワードと同様に、生の値を DB に保存すべきではない。
    SHA-256 は一方向ハッシュ（逆算不能）のため、DB が流出しても生のキーは復元できない。
    SHA-256 はパスワードハッシュとは異なり高速だが、API キーは十分なエントロピー（256 ビット）
    があるためレインボーテーブル攻撃が現実的でなく、SHA-256 で十分なセキュリティを確保できる。

    Args:
        raw_key: 生の API キー文字列（"fx_..." 形式）。

    Returns:
        str: SHA-256 ハッシュの 16 進数文字列（64 文字、例: "a3f8c2..."）。
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()


def api_key_prefix(raw_key: str) -> str:
    """
    API キーの先頭部分（プレフィックス）を取得する表示用ヘルパー関数。

    完全な API キーを表示する代わりに先頭 12 文字 + "..." を返すことで、
    ユーザーが「どのキーか」を視覚的に識別できるようにしつつ、機密情報の漏洩を防ぐ。

    例: "fx_AbCdEfGhIjKlMn..." → "fx_AbCdEfGhIj..."

    Args:
        raw_key: 生の API キー文字列。

    Returns:
        str: 先頭 12 文字 + "..."（12 文字以下の場合はそのまま返す）。
    """
    # 先頭 12 文字は "fx_" プレフィックスと英数字 9 文字（識別には十分）
    return raw_key[:12] + "..." if len(raw_key) > 12 else raw_key
