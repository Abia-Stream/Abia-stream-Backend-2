from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from profiles.models import Profile


class CustomAccountAdapter(DefaultAccountAdapter):
    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        user.role = 'viewer'
        user.status = 'active'
        user.is_email_verified = True
        if commit:
            user.save()
        return user


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        """
        Called when a new user signs in with Google for the first time.
        Creates the user and their profile.
        """
        user = super().save_user(request, sociallogin, form)

        # Set role and status for OAuth users
        user.role = 'viewer'
        user.status = 'active'
        user.is_email_verified = True
        user.save()

        # Extract name from Google profile data
        extra_data = sociallogin.account.extra_data
        full_name = extra_data.get('name', '')
        avatar_url = extra_data.get('picture', '')

        # Create profile if it doesn't exist
        Profile.objects.get_or_create(
            user=user,
            defaults={
                'full_name': full_name,
                'avatar_url': avatar_url,
            }
        )

        return user

    def is_open_for_signup(self, request, sociallogin):
        return True