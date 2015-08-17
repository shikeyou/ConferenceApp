# Conference App

---

## Introduction

This is Project 4 for Udacity's Full Stack Web Developer Nanodegree.

Main objectives of this project:

* Develop an API server hosted on a cloud-based hosting platform (Google App Engine)
* Enhance features of an existing conference app 

## Requirements

You will need these installed in your computer:

* [Python 2.x](https://www.python.org/downloads/)
* [Google App Engine SDK for Python](https://cloud.google.com/appengine/downloads)

## Files

These are the files that come with this project:

* **app.yaml:** Main configuration file that specifies configurations such as the mapping of urls to script files and listing of libraries used

* **conference.py** Main script file which contains the endpoint api and methods

* **cron.yaml** Specifies cron jobs to run

* **index.yaml** Specifies indices used to index the datastore entities

* **main.py** Contains request handler definitions such as those for updating featured speakers and sending out emails and  

* **models.py** Contains the model and message classes

* **settings.py** For global settings such as the client id

* **utils.py** Some basic helper util functions

## Running The Project

You will need an app id from Google first. 

* Go to [https://console.developers.google.com](https://console.developers.google.com) and login using your Google account

* Click on the Create Project button. A New Project dialog should appear.

* Give the project a suitable name (e.g. Conference App). Project ID can be left as default. Once you are done, click on the Create button. Note the application id.

Now that you have an application id, you can start working with the files.

* Clone the repository

* Open `app.yaml` and change the application (first line) to your application id

* Open Google App Engine Launcher and add the project

* Click on the run button to run the server locally. Note the port number for your project (e.g. 8080)

* In a web browser, go to http://localhost:<port\>/_ah/api/explorer to access the API Explorer

* You can use this API Explorer to interact with the system e.g. create speakers/sessions, query speaker/sessions etc

* Once you are done with testing locally, you can launch the project online. In Google App Engine Launcher, click on the Deploy button. Your app will appear in the url https://<app\_id\>.appspot.com/_ah/api/explorer


## Explanations

###Task 1: 

*Question: Explain in a couple of paragraphs your design choices for session and speaker implementation*

* `Session` is implemented as instructed. Some notes:
	* a `Session` entity is stored as a child of a `Conference` entity
	* multiple speakers are allowed for a session, `speakerKeys` is a list of websafe key for `Speaker`s
	* startTime is stored as a 4-digit integer in 24 hour notation in the form "HHMM", so that it is possible to pass this time as an url param

* `Speaker` is implemented as a kind  instead of just a plain name string so that:
	* it is possible to have additional info about a speaker (e.g. bio)
    * it is easier to update info about a speaker at one single location and have the updated info show up everywhere  

###Task 2:

I've implemented a wishlist as an array of `Session`s in the `Profile` class. This is a "has-a" relationship. Sessions are added into this array whenever the `addSessionToWishlist()` method is called.

This is under the assumption that there is only one single wishlist per user and that the user can add sessions from any conference into that one wishlist. 

###Task 3:

*Question: Think about other types of queries that would be useful for this application. Describe the purpose of 2 new queries and write the code that would perform them.*

* **getConferenceSessionsByDate(websafeConferenceKey, startDate, endDate):** will be helpful for users who are interested in sessions within a certain date range (e.g. August and September)

* **getConferenceSessionsByTime(websafeConferenceKey, startTime, endTime):** will be helpful for users who can only attend sessions within a certain daily time frame (e.g. after work from 6pm onwards)

*Question: Let's say you don't like workshops and you don't like sessions after 7pm. How would you handle a query for all non-workshop sessions before 7pm? What is the problem for implementing this query? What ways to solve it did you think of?*

* **Naive Solution:** do a query on Sessions, filtered with the inequalities as stated, but this will not work
	
		sessions = Session.query()
		sessions = sessions.filter(ndb.AND(Session.typeOfSession != 'WORKSHOP', Session.startTime <= 1900))

* **Problem:** Google datastore query inequality filters are limited to at most one property as a form of optimization to avoid scanning the entire index table ([https://cloud.google.com/appengine/docs/python/datastore/queries?hl=en#Python_Restrictions_on_queries](https://cloud.google.com/appengine/docs/python/datastore/queries?hl=en#Python_Restrictions_on_queries)), but the problem we have requires two inequality filters on two different properties (typeOfSession and startTime)

* **Workarounds:** 

	* Fetch all results using first inequality, then filter for the next inequality using Python
	
			sessions = Session.query()
			sessions = sessions.filter(Session.typeOfSession != 'WORKSHOP')
			sessions = [s for s in sessions if s.startTime <= 1900]

		This method is ok in this application because the number of sessions returned from the first filter would not be too large (it is uncommon to have 1 million sessions in one single conference), so Python, which is slower, won't be dealing with large amounts of data. This is the method that I have used in my codes.

	* Change the second inequality to an array of equalities, then merge the results

			results = []
			for t in range(0, 1900, 100)
				sessions = Session.query()
				sessions = sessions.filter(ndb.AND(Session.typeOfSession != 'WORKSHOP', Session.startTime == t))
				results.append(sessions)

		This method might be faster if there are potentially a lot of results from each filter (filtering is faster using a query rather than using Python), but it can only handle time intervals up to a certain granular level (every hour in this case), and that this uses up a lot more resources/quota in datastore. 

### Task 4

I've implemented `getFeaturedSpeaker()` to store a featured speaker per conference.

The memcache key used is "[websafeConferenceKey]_featuredSpeaker" e.g. ahtkZXZ-Y29uZmVyZW5jZS1jZW50cmFsLTEwMjlyLwsSB1Byb2ZpbGUiEnNoaWtleW91QGdtYWlsLmNvbQwLEgpDb25mZXJlbmNlGAEM\_featuredSpeaker