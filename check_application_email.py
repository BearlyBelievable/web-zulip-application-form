import os

from zerver.models import PreregistrationUser, UserProfile
from zerver.models.prereg_users import filter_to_valid_prereg_users

email = os.environ["CHECK_EMAIL"]

if UserProfile.objects.filter(delivery_email__iexact=email, is_active=True).exists():
    print("RESULT:registered")
elif filter_to_valid_prereg_users(
    PreregistrationUser.objects.filter(email__iexact=email), invitations_only=True
).exists():
    print("RESULT:invited")
else:
    print("RESULT:none")
