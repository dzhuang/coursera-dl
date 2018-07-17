from peewee import Model, ForeignKeyField, SqliteDatabase, CharField, TextField


database = SqliteDatabase("coursera-dl.db")


class BaseModel(Model):
    class Meta:
        database = database


class Course(BaseModel):
    course_id = CharField(unique=True)
    course_name_string = TextField()
    course_slug = CharField(unique=True)


class Module(BaseModel):
    module_id = CharField(unique=True)
    course = ForeignKeyField(Course, backref="modules")
    description = TextField(default="")
    name = TextField(default="")
    slug = TextField(default="")


class Lesson(BaseModel):
    lesson_id = CharField(unique=True)
    module = ForeignKeyField(Module, backref="lessons")
    name = TextField(default="")
    slug = TextField(default="")


class Item(BaseModel):
    item_id = CharField(unique=True)
    lesson = ForeignKeyField(Lesson, backref="items")
    module = ForeignKeyField(Module, backref="items")
    name = TextField(default="")
    slug = TextField(default="")
    type_name = CharField(default="")
    content = TextField(default="")


class CourseAsset(BaseModel):
    asset_id = CharField(unique=True)
    asset_type = CharField(default="")
    slug = TextField(default="")
    name = TextField(default="")
    saved_path = CharField(default="")


class ItemVideoAsset(BaseModel):
    asset_id = CharField(unique=True)
    item = ForeignKeyField(Item, backref="itemvideoasset")
    subtitles = CharField(default="")
    saved_path = CharField(default="")


class ItemAsset(BaseModel):
    item = ForeignKeyField(Item, backref="itemasset")
    asset = ForeignKeyField(CourseAsset, backref="itemasset")


class Reference(BaseModel):
    ref_id = CharField(unique=True)
    course = ForeignKeyField(Course, backref="reference")
    short_id = CharField(unique=True)
    slug = TextField(default="")
    name = TextField(default="")
    value = TextField(default="")
    content = TextField(default="")


def create_tables():
    with database:
        database.create_tables(
            [Course, Module, Lesson, Item, CourseAsset, ItemAsset,
             Reference, ItemVideoAsset],
            safe=True)
