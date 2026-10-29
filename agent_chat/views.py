from django.views import View
from django.shortcuts import render

class ChatView(View):
    template_name = "chat.html"

    def get(self, request):
        if request.session.session_key is None:
            request.session.create()
        return render(request, self.template_name)