"""Transactional, checksum-verified additive migrations; never rebuild existing data."""
from hashlib import sha256
from pathlib import Path

ROOT=Path(__file__).parent/'migrations'
FILES={1:'001_existing_schema.sql',2:'002_controlled_ai_runs.sql',3:'003_attempt_reviews.sql'}


def _manifest():
    return {version:(name,(ROOT/name).read_text('utf-8')) for version,name in FILES.items()}


def _lock_and_read(db, manifest):
    db.execute('select pg_advisory_xact_lock(618114000)')
    db.execute("""create table if not exists schema_migrations(
        version integer primary key, name text not null, checksum text not null,
        applied_at timestamptz not null default clock_timestamp())""")
    rows=db.execute('select version,name,checksum from schema_migrations order by version').fetchall()
    for row in rows:
        entry=manifest.get(row['version'])
        if not entry or row['name']!=entry[0] or row['checksum']!=sha256(entry[1].encode()).hexdigest():
            raise ValueError('Migration history is unknown or its checksum changed; no migration applied.')
    versions=[row['version'] for row in rows]
    if versions!=list(range(1,len(versions)+1)):
        raise ValueError('Migration history is not contiguous.')
    return versions


def upgrade(db, target=None):
    manifest=_manifest()
    target=max(manifest) if target is None else target
    if type(target) is not int or target not in manifest:
        raise ValueError('Unknown migration target.')
    with db.transaction():
        versions=_lock_and_read(db,manifest)
        if versions and target<max(versions):
            raise ValueError('Use the explicit downgrade operation.')
        for version,(name,sql) in manifest.items():
            if version<=target and version not in versions:
                db.execute(sql)
                db.execute('insert into schema_migrations(version,name,checksum) values(%s,%s,%s)',
                           (version,name,sha256(sql.encode()).hexdigest()))
    return target


def downgrade(db, target):
    # Baseline data is never dropped; populated ledgers/reviews refuse removal.
    if type(target) is not int or target not in FILES:
        raise ValueError('Unknown downgrade target.')
    with db.transaction():
        versions=_lock_and_read(db,_manifest())
        for version in reversed(versions):
            if version>target:
                path=ROOT/FILES[version].replace('.sql','.down.sql')
                db.execute(path.read_text('utf-8'))
                db.execute('delete from schema_migrations where version=%s',(version,))
    return target
