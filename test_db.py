from db.mongo import users_col

users_col.insert_one({"test": "Mongo is connected 🔥"})
print("Mongo connected successfully ✅")
